"""Tests for peer list distribution and NAT traversal logic."""
import pytest
from httpx import AsyncClient

ADMIN_TOKEN = "test-admin-token"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _register(
    client: AsyncClient,
    name: str,
    key: str,
    endpoint_ip: str = "1.2.3.4",
) -> tuple[str, str]:
    resp = await client.post(
        "/api/v1/nodes/register",
        json={
            "name": name,
            "wireguard_public_key": key,
            "endpoint_ip": endpoint_ip,
            "endpoint_port": 51820,
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return data["id"], data["auth_token"]


async def _activate(client: AsyncClient, node_id: str) -> None:
    resp = await client.patch(
        f"/api/v1/nodes/{node_id}/activate",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200, resp.text


async def _register_and_activate(
    client: AsyncClient,
    name: str,
    key: str,
    endpoint_ip: str = "1.2.3.4",
) -> tuple[str, str]:
    node_id, token = await _register(client, name, key, endpoint_ip)
    await _activate(client, node_id)
    return node_id, token


# ---------------------------------------------------------------------------
# Peer list correctness
# ---------------------------------------------------------------------------


async def test_peers_excludes_self(client: AsyncClient):
    n1_id, t1 = await _register_and_activate(client, "node1", "k1==")
    n2_id, t2 = await _register_and_activate(client, "node2", "k2==")
    n3_id, t3 = await _register_and_activate(client, "node3", "k3==")

    resp = await client.get(
        f"/api/v1/nodes/{n1_id}/peers",
        headers={"Authorization": f"Bearer {t1}"},
    )
    assert resp.status_code == 200
    names = {p["name"] for p in resp.json()}
    assert "node1" not in names
    assert names == {"node2", "node3"}


async def test_peers_excludes_pending_nodes(client: AsyncClient):
    n1_id, t1 = await _register_and_activate(client, "node1", "k1==")
    await _register(client, "node2", "k2==")  # not activated

    resp = await client.get(
        f"/api/v1/nodes/{n1_id}/peers",
        headers={"Authorization": f"Bearer {t1}"},
    )
    assert resp.status_code == 200
    assert resp.json() == []


async def test_peers_excludes_revoked_nodes(client: AsyncClient):
    n1_id, t1 = await _register_and_activate(client, "node1", "k1==")
    n2_id, t2 = await _register_and_activate(client, "node2", "k2==")

    await client.delete(
        f"/api/v1/nodes/{n2_id}/revoke",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )

    resp = await client.get(
        f"/api/v1/nodes/{n1_id}/peers",
        headers={"Authorization": f"Bearer {t1}"},
    )
    assert resp.status_code == 200
    assert resp.json() == []


async def test_peers_returns_correct_fields(client: AsyncClient):
    n1_id, t1 = await _register_and_activate(
        client, "branch-sydney", "sydney-key==", endpoint_ip="203.0.113.1"
    )
    n2_id, t2 = await _register_and_activate(
        client, "branch-london", "london-key==", endpoint_ip="198.51.100.1"
    )

    resp = await client.get(
        f"/api/v1/nodes/{n2_id}/peers",
        headers={"Authorization": f"Bearer {t2}"},
    )
    assert resp.status_code == 200
    peers = resp.json()
    assert len(peers) == 1
    peer = peers[0]
    assert peer["name"] == "branch-sydney"
    assert peer["wireguard_public_key"] == "sydney-key=="
    assert peer["endpoint_port"] == 51820
    assert "vpn_ip" in peer
    assert "preferred_endpoint" in peer
    assert "nat_detected" in peer


# ---------------------------------------------------------------------------
# NAT detection logic
# ---------------------------------------------------------------------------


async def test_nat_detected_when_reflected_differs(client: AsyncClient):
    """
    endpoint_ip="1.2.3.4" but the ASGI transport always reports the client
    host as "127.0.0.1", so reflected_endpoint_ip != endpoint_ip → NAT.
    The preferred_endpoint should be the reflected IP.
    """
    n1_id, t1 = await _register_and_activate(
        client, "node1", "k1==", endpoint_ip="1.2.3.4"
    )
    n2_id, t2 = await _register_and_activate(
        client, "node2", "k2==", endpoint_ip="5.6.7.8"
    )

    resp = await client.get(
        f"/api/v1/nodes/{n2_id}/peers",
        headers={"Authorization": f"Bearer {t2}"},
    )
    assert resp.status_code == 200
    peers = resp.json()
    assert len(peers) == 1
    peer = peers[0]
    # reflected="127.0.0.1" ≠ endpoint_ip="1.2.3.4" → NAT
    assert peer["nat_detected"] is True
    assert peer["preferred_endpoint"] == "127.0.0.1"


async def test_nat_not_detected_when_ips_match(client: AsyncClient):
    """
    When endpoint_ip equals the reflected IP, no NAT is detected.
    We set endpoint_ip="127.0.0.1" to match what ASGI transport reports.
    """
    n1_id, t1 = await _register_and_activate(
        client, "node1", "k1==", endpoint_ip="127.0.0.1"
    )
    n2_id, t2 = await _register_and_activate(
        client, "node2", "k2==", endpoint_ip="127.0.0.1"
    )

    resp = await client.get(
        f"/api/v1/nodes/{n2_id}/peers",
        headers={"Authorization": f"Bearer {t2}"},
    )
    assert resp.status_code == 200
    peers = resp.json()
    assert len(peers) == 1
    peer = peers[0]
    assert peer["nat_detected"] is False
    assert peer["preferred_endpoint"] == "127.0.0.1"


# ---------------------------------------------------------------------------
# Auth enforcement
# ---------------------------------------------------------------------------


async def test_peers_requires_auth(client: AsyncClient):
    n1_id, t1 = await _register_and_activate(client, "node1", "k1==")

    resp = await client.get(
        f"/api/v1/nodes/{n1_id}/peers",
        headers={"Authorization": "Bearer bogus"},
    )
    assert resp.status_code == 401


async def test_peers_wrong_node_token_forbidden(client: AsyncClient):
    """Token from node2 must not be usable to fetch node1's peer list."""
    n1_id, t1 = await _register_and_activate(client, "node1", "k1==")
    n2_id, t2 = await _register_and_activate(client, "node2", "k2==")

    resp = await client.get(
        f"/api/v1/nodes/{n1_id}/peers",
        headers={"Authorization": f"Bearer {t2}"},
    )
    assert resp.status_code == 403
