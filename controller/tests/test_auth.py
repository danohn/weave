"""Tests for pre-auth token management and token-gated node registration."""
import pytest
from httpx import AsyncClient

ADMIN_TOKEN = "test-admin-token"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def create_token(client: AsyncClient, label: str = "test-token") -> dict:
    resp = await client.post(
        "/api/v1/auth/tokens",
        json={"label": label},
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 201
    return resp.json()


def node_payload(**overrides) -> dict:
    defaults = {
        "name": "branch-sydney",
        "wireguard_public_key": "abc123pubkey==",
        "endpoint_ip": "1.2.3.4",
        "endpoint_port": 51820,
    }
    return {**defaults, **overrides}


# ---------------------------------------------------------------------------
# Token CRUD
# ---------------------------------------------------------------------------


async def test_create_token(client: AsyncClient):
    data = await create_token(client, label="batch-2025-04")
    assert "id" in data
    assert "token" in data
    assert data["label"] == "batch-2025-04"
    assert data["used_at"] is None
    assert data["used_by_node_id"] is None
    assert len(data["token"]) > 20


async def test_create_token_requires_admin(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/tokens",
        json={"label": "x"},
        headers={"Authorization": "Bearer wrong"},
    )
    assert resp.status_code == 401


async def test_list_tokens(client: AsyncClient):
    await create_token(client, label="t1")
    await create_token(client, label="t2")

    resp = await client.get(
        "/api/v1/auth/tokens",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_list_tokens_requires_admin(client: AsyncClient):
    resp = await client.get(
        "/api/v1/auth/tokens",
        headers={"Authorization": "Bearer wrong"},
    )
    assert resp.status_code == 401


async def test_delete_unused_token(client: AsyncClient):
    token = await create_token(client)

    resp = await client.delete(
        f"/api/v1/auth/tokens/{token['id']}",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 204

    # Should be gone
    list_resp = await client.get(
        "/api/v1/auth/tokens",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert list_resp.json() == []


async def test_delete_used_token_rejected(client: AsyncClient):
    token = await create_token(client)

    # Consume the token via registration
    await client.post(
        "/api/v1/nodes/register",
        json=node_payload(preauth_token=token["token"]),
    )

    resp = await client.delete(
        f"/api/v1/auth/tokens/{token['id']}",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 400


async def test_delete_nonexistent_token(client: AsyncClient):
    resp = await client.delete(
        "/api/v1/auth/tokens/does-not-exist",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Registration with pre-auth token
# ---------------------------------------------------------------------------


async def test_register_with_valid_token_activates_immediately(client: AsyncClient):
    token = await create_token(client)

    resp = await client.post(
        "/api/v1/nodes/register",
        json=node_payload(preauth_token=token["token"]),
    )
    assert resp.status_code == 201

    # Node should be ACTIVE without admin intervention
    node_id = resp.json()["id"]
    node_token = resp.json()["auth_token"]
    hb = await client.post(
        f"/api/v1/nodes/{node_id}/heartbeat",
        headers={"Authorization": f"Bearer {node_token}"},
    )
    assert hb.json()["status"] == "ACTIVE"


async def test_register_with_valid_token_marks_token_used(client: AsyncClient):
    token = await create_token(client)

    await client.post(
        "/api/v1/nodes/register",
        json=node_payload(preauth_token=token["token"]),
    )

    list_resp = await client.get(
        "/api/v1/auth/tokens",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    t = list_resp.json()[0]
    assert t["used_at"] is not None
    assert t["used_by_node_id"] is not None


async def test_register_token_cannot_be_reused(client: AsyncClient):
    token = await create_token(client)

    await client.post(
        "/api/v1/nodes/register",
        json=node_payload(preauth_token=token["token"]),
    )

    resp = await client.post(
        "/api/v1/nodes/register",
        json=node_payload(name="node2", wireguard_public_key="key2==", preauth_token=token["token"]),
    )
    assert resp.status_code == 401
    assert "already-used" in resp.json()["detail"]


async def test_register_invalid_token_rejected(client: AsyncClient):
    resp = await client.post(
        "/api/v1/nodes/register",
        json=node_payload(preauth_token="totally-fake-token"),
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# REQUIRE_PREAUTH enforcement (tested via a sub-app with the flag on)
# ---------------------------------------------------------------------------


@pytest.mark.require_preauth
async def test_register_without_token_rejected_when_required(
    client_require_preauth: AsyncClient,
):
    resp = await client_require_preauth.post(
        "/api/v1/nodes/register",
        json=node_payload(),
    )
    assert resp.status_code == 401
    assert "pre-auth token is required" in resp.json()["detail"]


@pytest.mark.require_preauth
async def test_register_with_token_accepted_when_required(
    client_require_preauth: AsyncClient,
):
    # Create a token using the preauth client (shares same DB via override)
    token_resp = await client_require_preauth.post(
        "/api/v1/auth/tokens",
        json={"label": "required-test"},
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    token = token_resp.json()["token"]

    resp = await client_require_preauth.post(
        "/api/v1/nodes/register",
        json=node_payload(preauth_token=token),
    )
    assert resp.status_code == 201
