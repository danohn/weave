"""Tests for device-claim management and claim-gated node registration."""
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

ADMIN_TOKEN = "test-admin-token"


async def create_claim(client: AsyncClient, **overrides) -> dict:
    payload = {
        "device_id": "branch-sydney-01",
        "site_name": "sydney",
        "expected_name": "branch-sydney",
        "site_subnet": "192.168.10.0/24",
        **overrides,
    }
    resp = await client.post(
        "/api/v1/auth/claims",
        json=payload,
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 201
    return resp.json()


def node_payload(**overrides) -> dict:
    defaults = {
        "name": "branch-sydney",
        "wireguard_public_key": "abc123pubkey==",
        "endpoint_port": 51820,
    }
    return {**defaults, **overrides}


async def test_create_claim(client: AsyncClient):
    data = await create_claim(client)
    assert "id" in data
    assert "token" in data
    assert data["device_id"] == "branch-sydney-01"
    assert data["status"] == "UNCLAIMED"
    assert data["claimed_at"] is None
    assert data["claimed_by_node_id"] is None
    assert data["token"].startswith(data["token_prefix"])


async def test_create_claim_requires_admin(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/claims",
        json={"device_id": "x"},
        headers={"Authorization": "Bearer wrong"},
    )
    assert resp.status_code == 401


async def test_list_claims(client: AsyncClient):
    await create_claim(client, device_id="claim-1")
    await create_claim(client, device_id="claim-2", expected_name="node-2")

    resp = await client.get(
        "/api/v1/auth/claims",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200
    claims = resp.json()
    assert len(claims) == 2
    for claim in claims:
        assert "token" not in claim
        assert "token_prefix" in claim


async def test_delete_unused_claim(client: AsyncClient):
    claim = await create_claim(client)

    resp = await client.delete(
        f"/api/v1/auth/claims/{claim['id']}",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 204


async def test_delete_used_claim_rejected(client: AsyncClient):
    claim = await create_claim(client)
    await client.post(
        "/api/v1/nodes/register",
        json=node_payload(claim_token=claim["token"]),
    )

    resp = await client.delete(
        f"/api/v1/auth/claims/{claim['id']}",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 400


async def test_revoke_claim(client: AsyncClient):
    claim = await create_claim(client)

    resp = await client.post(
        f"/api/v1/auth/claims/{claim['id']}/revoke",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "REVOKED"


async def test_register_with_valid_claim_activates_immediately(client: AsyncClient):
    claim = await create_claim(client)

    resp = await client.post(
        "/api/v1/nodes/register",
        json=node_payload(claim_token=claim["token"]),
    )
    assert resp.status_code == 201
    assert resp.json()["device_claim_id"] == claim["id"]

    node_id = resp.json()["id"]
    node_token = resp.json()["auth_token"]
    hb = await client.post(
        f"/api/v1/nodes/{node_id}/heartbeat",
        headers={"Authorization": f"Bearer {node_token}"},
    )
    assert hb.json()["status"] == "ACTIVE"


async def test_register_with_claim_marks_claim_active(client: AsyncClient):
    claim = await create_claim(client)

    reg = await client.post(
        "/api/v1/nodes/register",
        json=node_payload(claim_token=claim["token"]),
    )
    assert reg.status_code == 201

    list_resp = await client.get(
        "/api/v1/auth/claims",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    stored = next(x for x in list_resp.json() if x["id"] == claim["id"])
    assert stored["status"] == "ACTIVE"
    assert stored["claimed_at"] is not None
    assert stored["claimed_by_node_id"] == reg.json()["id"]


async def test_register_claim_cannot_be_reused(client: AsyncClient):
    claim = await create_claim(client)

    await client.post(
        "/api/v1/nodes/register",
        json=node_payload(claim_token=claim["token"]),
    )

    resp = await client.post(
        "/api/v1/nodes/register",
        json=node_payload(
            name="node2",
            wireguard_public_key="key2==",
            claim_token=claim["token"],
        ),
    )
    assert resp.status_code == 401
    assert "already been used" in resp.json()["detail"]


async def test_register_invalid_claim_rejected(client: AsyncClient):
    resp = await client.post(
        "/api/v1/nodes/register",
        json=node_payload(claim_token="totally-fake-token"),
    )
    assert resp.status_code == 401


async def test_register_rejects_name_mismatch(client: AsyncClient):
    claim = await create_claim(client, expected_name="expected-name")
    resp = await client.post(
        "/api/v1/nodes/register",
        json=node_payload(name="other-name", claim_token=claim["token"]),
    )
    assert resp.status_code == 409


async def test_register_rejects_expired_claim(client: AsyncClient):
    claim = await create_claim(
        client, expires_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    )
    resp = await client.post(
        "/api/v1/nodes/register",
        json=node_payload(claim_token=claim["token"]),
    )
    assert resp.status_code == 401
    assert "expired" in resp.json()["detail"]


@pytest.mark.require_preauth
async def test_register_without_claim_rejected_when_required(
    client_require_preauth: AsyncClient,
):
    resp = await client_require_preauth.post(
        "/api/v1/nodes/register",
        json=node_payload(),
    )
    assert resp.status_code == 401
    assert "claim token is required" in resp.json()["detail"]


@pytest.mark.require_preauth
async def test_register_with_claim_accepted_when_required(
    client_require_preauth: AsyncClient,
):
    claim_resp = await client_require_preauth.post(
        "/api/v1/auth/claims",
        json={"device_id": "required-test"},
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    token = claim_resp.json()["token"]

    resp = await client_require_preauth.post(
        "/api/v1/nodes/register",
        json=node_payload(claim_token=token),
    )
    assert resp.status_code == 201
