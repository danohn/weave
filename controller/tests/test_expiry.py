"""Tests for stale-node expiry and VPN IP auto-allocation."""
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.models import Node, NodeStatus
from app.services import node_service

ADMIN_TOKEN = "test-admin-token"


def node_payload(**overrides) -> dict:
    defaults = {
        "name": "branch-sydney",
        "wireguard_public_key": "abc123pubkey==",
        "endpoint_ip": "1.2.3.4",
        "endpoint_port": 51820,
    }
    return {**defaults, **overrides}


async def _activate(client, node_id):
    resp = await client.patch(
        f"/api/v1/nodes/{node_id}/activate",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# VPN IP auto-allocation
# ---------------------------------------------------------------------------


async def test_vpn_ip_auto_assigned(client: AsyncClient):
    resp = await client.post("/api/v1/nodes/register", json=node_payload())
    assert resp.status_code == 201
    assert "vpn_ip" in resp.json()


async def test_vpn_ip_first_host_in_subnet(client: AsyncClient):
    """First registered node gets the first usable host (10.0.0.1 in /24)."""
    resp = await client.post("/api/v1/nodes/register", json=node_payload())
    assert resp.json()["vpn_ip"] == "10.0.0.1"


async def test_vpn_ip_sequential_allocation(client: AsyncClient):
    """Each new node gets the next available address."""
    ips = []
    for i in range(3):
        r = await client.post(
            "/api/v1/nodes/register",
            json=node_payload(name=f"node{i}", wireguard_public_key=f"key{i}=="),
        )
        ips.append(r.json()["vpn_ip"])
    assert ips == ["10.0.0.1", "10.0.0.2", "10.0.0.3"]


async def test_vpn_ip_unique_per_node(client: AsyncClient):
    r1 = await client.post(
        "/api/v1/nodes/register",
        json=node_payload(name="n1", wireguard_public_key="k1=="),
    )
    r2 = await client.post(
        "/api/v1/nodes/register",
        json=node_payload(name="n2", wireguard_public_key="k2=="),
    )
    assert r1.json()["vpn_ip"] != r2.json()["vpn_ip"]


async def test_revoked_node_ip_not_reused(client: AsyncClient, make_session):
    """A revoked node's VPN IP stays allocated; new nodes get the next address."""
    r1 = await client.post(
        "/api/v1/nodes/register",
        json=node_payload(name="n1", wireguard_public_key="k1=="),
    )
    n1_id = r1.json()["id"]
    first_ip = r1.json()["vpn_ip"]

    await client.delete(
        f"/api/v1/nodes/{n1_id}/revoke",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )

    r2 = await client.post(
        "/api/v1/nodes/register",
        json=node_payload(name="n2", wireguard_public_key="k2=="),
    )
    second_ip = r2.json()["vpn_ip"]
    assert second_ip != first_ip


# ---------------------------------------------------------------------------
# Stale-node expiry
# ---------------------------------------------------------------------------


async def test_stale_node_marked_offline(client: AsyncClient, make_session):
    reg = await client.post("/api/v1/nodes/register", json=node_payload())
    node_id = reg.json()["id"]
    await _activate(client, node_id)

    # Backdate last_seen beyond the threshold
    old = datetime.now(timezone.utc) - timedelta(seconds=200)
    async with make_session() as db:
        node = (await db.execute(select(Node).where(Node.id == node_id))).scalar_one()
        node.last_seen = old
        await db.commit()

    async with make_session() as db:
        expired = await node_service.expire_stale_nodes(db, threshold_seconds=120)
    assert expired == 1

    admin_resp = await client.get(
        "/api/v1/nodes/",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert admin_resp.json()[0]["status"] == "OFFLINE"


async def test_fresh_node_not_expired(client: AsyncClient, make_session):
    reg = await client.post("/api/v1/nodes/register", json=node_payload())
    await _activate(client, reg.json()["id"])

    async with make_session() as db:
        expired = await node_service.expire_stale_nodes(db, threshold_seconds=120)
    assert expired == 0


async def test_only_active_nodes_are_expired(client: AsyncClient, make_session):
    """PENDING and REVOKED nodes must not be transitioned to OFFLINE."""
    pending_reg = await client.post(
        "/api/v1/nodes/register",
        json=node_payload(name="pending-node", wireguard_public_key="pk=="),
    )
    revoked_reg = await client.post(
        "/api/v1/nodes/register",
        json=node_payload(name="revoked-node", wireguard_public_key="rk=="),
    )
    revoked_id = revoked_reg.json()["id"]
    await _activate(client, revoked_id)
    await client.delete(
        f"/api/v1/nodes/{revoked_id}/revoke",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )

    # Backdate both nodes
    old = datetime.now(timezone.utc) - timedelta(seconds=300)
    for node_id in (pending_reg.json()["id"], revoked_id):
        async with make_session() as db:
            node = (
                await db.execute(select(Node).where(Node.id == node_id))
            ).scalar_one()
            node.last_seen = old
            await db.commit()

    async with make_session() as db:
        expired = await node_service.expire_stale_nodes(db, threshold_seconds=120)
    assert expired == 0


async def test_offline_node_excluded_from_peers(client: AsyncClient, make_session):
    r1 = await client.post(
        "/api/v1/nodes/register",
        json=node_payload(name="n1", wireguard_public_key="k1=="),
    )
    n1_id, t1 = r1.json()["id"], r1.json()["auth_token"]
    await _activate(client, n1_id)

    r2 = await client.post(
        "/api/v1/nodes/register",
        json=node_payload(name="n2", wireguard_public_key="k2=="),
    )
    n2_id = r2.json()["id"]
    await _activate(client, n2_id)

    # Mark n2 offline directly
    async with make_session() as db:
        node = (await db.execute(select(Node).where(Node.id == n2_id))).scalar_one()
        node.status = NodeStatus.OFFLINE
        await db.commit()

    resp = await client.get(
        f"/api/v1/nodes/{n1_id}/peers",
        headers={"Authorization": f"Bearer {t1}"},
    )
    assert resp.status_code == 200
    assert resp.json() == []


async def test_offline_node_recovers_on_heartbeat(client: AsyncClient, make_session):
    reg = await client.post("/api/v1/nodes/register", json=node_payload())
    node_id, token = reg.json()["id"], reg.json()["auth_token"]
    await _activate(client, node_id)

    # Force to OFFLINE
    async with make_session() as db:
        node = (await db.execute(select(Node).where(Node.id == node_id))).scalar_one()
        node.status = NodeStatus.OFFLINE
        await db.commit()

    # Heartbeat should restore ACTIVE
    hb = await client.post(
        f"/api/v1/nodes/{node_id}/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert hb.status_code == 200
    assert hb.json()["status"] == "ACTIVE"


async def test_revoked_node_heartbeat_rejected(client: AsyncClient):
    reg = await client.post("/api/v1/nodes/register", json=node_payload())
    node_id, token = reg.json()["id"], reg.json()["auth_token"]

    await client.delete(
        f"/api/v1/nodes/{node_id}/revoke",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )

    resp = await client.post(
        f"/api/v1/nodes/{node_id}/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
