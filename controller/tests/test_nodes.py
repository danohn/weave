"""Tests for node registration, heartbeat, and admin management."""

from httpx import AsyncClient

ADMIN_TOKEN = "test-admin-token"


def node_payload(**overrides) -> dict:
    defaults = {
        "name": "branch-sydney",
        "wireguard_public_key": "abc123pubkey==",
        "endpoint_ip": "1.2.3.4",
        "endpoint_port": 51820,
        # vpn_ip is now auto-assigned by the controller
    }
    return {**defaults, **overrides}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


async def test_register_node_happy_path(client: AsyncClient):
    response = await client.post("/api/v1/nodes/register", json=node_payload())
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert "auth_token" in data
    assert "vpn_ip" in data
    assert len(data["auth_token"]) > 20


async def test_register_assigns_vpn_ip(client: AsyncClient):
    """Registered node receives a VPN IP from the configured subnet."""
    response = await client.post("/api/v1/nodes/register", json=node_payload())
    assert response.status_code == 201
    vpn_ip = response.json()["vpn_ip"]
    # Default subnet is 10.0.0.0/24 in tests
    assert vpn_ip.startswith("10.0.0.")


async def test_register_populates_reflected_ip(client: AsyncClient):
    """Controller captures request.client.host as reflected_endpoint_ip."""
    await client.post("/api/v1/nodes/register", json=node_payload())

    admin_resp = await client.get(
        "/api/v1/nodes/",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    nodes = admin_resp.json()
    assert len(nodes) == 1
    # httpx ASGITransport reports 127.0.0.1 as the client host
    assert nodes[0]["reflected_endpoint_ip"] == "127.0.0.1"


async def test_register_duplicate_name_rejected(client: AsyncClient):
    await client.post("/api/v1/nodes/register", json=node_payload())
    response = await client.post(
        "/api/v1/nodes/register",
        json=node_payload(wireguard_public_key="different-key=="),
    )
    assert response.status_code == 409
    assert "name" in response.json()["detail"].lower()


async def test_register_duplicate_key_rejected(client: AsyncClient):
    await client.post("/api/v1/nodes/register", json=node_payload())
    response = await client.post(
        "/api/v1/nodes/register",
        json=node_payload(name="branch-london"),
    )
    assert response.status_code == 409
    assert "key" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


async def test_heartbeat_updates_last_seen(client: AsyncClient):
    reg = await client.post("/api/v1/nodes/register", json=node_payload())
    data = reg.json()
    node_id, token = data["id"], data["auth_token"]

    response = await client.post(
        f"/api/v1/nodes/{node_id}/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    hb = response.json()
    assert "last_seen" in hb
    assert hb["status"] == "PENDING"


async def test_heartbeat_updates_reflected_ip(client: AsyncClient):
    """Heartbeat refreshes reflected_endpoint_ip from current request origin."""
    reg = await client.post("/api/v1/nodes/register", json=node_payload())
    data = reg.json()
    node_id, token = data["id"], data["auth_token"]

    await client.post(
        f"/api/v1/nodes/{node_id}/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
    )

    admin_resp = await client.get(
        "/api/v1/nodes/",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    node_data = admin_resp.json()[0]
    assert node_data["reflected_endpoint_ip"] == "127.0.0.1"


async def test_heartbeat_wrong_node_forbidden(client: AsyncClient):
    """A node cannot send heartbeats on behalf of another node."""
    reg1 = await client.post(
        "/api/v1/nodes/register",
        json=node_payload(name="node1", wireguard_public_key="key1=="),
    )
    reg2 = await client.post(
        "/api/v1/nodes/register",
        json=node_payload(name="node2", wireguard_public_key="key2=="),
    )
    node1_id = reg1.json()["id"]
    token2 = reg2.json()["auth_token"]

    response = await client.post(
        f"/api/v1/nodes/{node1_id}/heartbeat",
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert response.status_code == 403


async def test_heartbeat_invalid_token(client: AsyncClient):
    reg = await client.post("/api/v1/nodes/register", json=node_payload())
    node_id = reg.json()["id"]

    response = await client.post(
        f"/api/v1/nodes/{node_id}/heartbeat",
        headers={"Authorization": "Bearer totally-invalid"},
    )
    assert response.status_code == 401


async def test_rotate_token_replaces_old_token(client: AsyncClient):
    reg = await client.post("/api/v1/nodes/register", json=node_payload())
    node_id = reg.json()["id"]
    old_token = reg.json()["auth_token"]

    rotate = await client.post(
        f"/api/v1/nodes/{node_id}/rotate-token",
        headers={"Authorization": f"Bearer {old_token}"},
    )
    assert rotate.status_code == 200
    new_token = rotate.json()["auth_token"]
    assert new_token != old_token

    old_hb = await client.post(
        f"/api/v1/nodes/{node_id}/heartbeat",
        headers={"Authorization": f"Bearer {old_token}"},
    )
    assert old_hb.status_code == 401

    new_hb = await client.post(
        f"/api/v1/nodes/{node_id}/heartbeat",
        headers={"Authorization": f"Bearer {new_token}"},
    )
    assert new_hb.status_code == 200


async def test_rotate_token_wrong_node_forbidden(client: AsyncClient):
    reg1 = await client.post(
        "/api/v1/nodes/register",
        json=node_payload(name="node1", wireguard_public_key="key1=="),
    )
    reg2 = await client.post(
        "/api/v1/nodes/register",
        json=node_payload(name="node2", wireguard_public_key="key2=="),
    )

    response = await client.post(
        f"/api/v1/nodes/{reg1.json()['id']}/rotate-token",
        headers={"Authorization": f"Bearer {reg2.json()['auth_token']}"},
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Admin: activate
# ---------------------------------------------------------------------------


async def test_activate_node(client: AsyncClient):
    reg = await client.post("/api/v1/nodes/register", json=node_payload())
    node_id = reg.json()["id"]

    response = await client.patch(
        f"/api/v1/nodes/{node_id}/activate",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ACTIVE"


async def test_activate_requires_admin_token(client: AsyncClient):
    reg = await client.post("/api/v1/nodes/register", json=node_payload())
    node_id = reg.json()["id"]

    node_token = reg.json()["auth_token"]
    response = await client.patch(
        f"/api/v1/nodes/{node_id}/activate",
        headers={"Authorization": f"Bearer {node_token}"},
    )
    assert response.status_code == 401


async def test_activate_already_active_rejected(client: AsyncClient):
    reg = await client.post("/api/v1/nodes/register", json=node_payload())
    node_id = reg.json()["id"]

    await client.patch(
        f"/api/v1/nodes/{node_id}/activate",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    response = await client.patch(
        f"/api/v1/nodes/{node_id}/activate",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Admin: revoke
# ---------------------------------------------------------------------------


async def test_revoke_node(client: AsyncClient):
    reg = await client.post("/api/v1/nodes/register", json=node_payload())
    node_id = reg.json()["id"]

    await client.patch(
        f"/api/v1/nodes/{node_id}/activate",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )

    response = await client.delete(
        f"/api/v1/nodes/{node_id}/revoke",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "REVOKED"


async def test_revoke_requires_admin_token(client: AsyncClient):
    reg = await client.post("/api/v1/nodes/register", json=node_payload())
    node_id = reg.json()["id"]

    response = await client.delete(
        f"/api/v1/nodes/{node_id}/revoke",
        headers={"Authorization": "Bearer wrong"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Admin: delete
# ---------------------------------------------------------------------------


async def test_delete_node_removes_it(client: AsyncClient):
    reg = await client.post("/api/v1/nodes/register", json=node_payload())
    node_id = reg.json()["id"]

    response = await client.delete(
        f"/api/v1/nodes/{node_id}",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert response.status_code == 204

    list_resp = await client.get(
        "/api/v1/nodes/",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert list_resp.json() == []


async def test_delete_node_frees_vpn_ip(client: AsyncClient):
    """VPN IP is reassigned after the original node is deleted."""
    reg1 = await client.post("/api/v1/nodes/register", json=node_payload())
    ip1 = reg1.json()["vpn_ip"]
    node1_id = reg1.json()["id"]

    await client.delete(
        f"/api/v1/nodes/{node1_id}",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )

    reg2 = await client.post(
        "/api/v1/nodes/register",
        json=node_payload(name="node2", wireguard_public_key="key2=="),
    )
    assert reg2.json()["vpn_ip"] == ip1


async def test_delete_node_nullifies_claim_reference(client: AsyncClient):
    """Deleting a node clears claimed_by_node_id on the device claim."""
    claim_resp = await client.post(
        "/api/v1/auth/claims",
        json={"device_id": "delete-test"},
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    token = claim_resp.json()["token"]
    claim_id = claim_resp.json()["id"]

    reg = await client.post(
        "/api/v1/nodes/register",
        json=node_payload(claim_token=token),
    )
    node_id = reg.json()["id"]

    await client.delete(
        f"/api/v1/nodes/{node_id}",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )

    claims = await client.get(
        "/api/v1/auth/claims",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    claim = next(x for x in claims.json() if x["id"] == claim_id)
    assert claim["claimed_by_node_id"] is None


async def test_delete_node_requires_admin(client: AsyncClient):
    reg = await client.post("/api/v1/nodes/register", json=node_payload())
    node_id = reg.json()["id"]

    response = await client.delete(
        f"/api/v1/nodes/{node_id}",
        headers={"Authorization": "Bearer wrong"},
    )
    assert response.status_code == 401


async def test_delete_nonexistent_node(client: AsyncClient):
    response = await client.delete(
        "/api/v1/nodes/does-not-exist",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Admin: list
# ---------------------------------------------------------------------------


async def test_list_nodes(client: AsyncClient):
    for i in range(3):
        await client.post(
            "/api/v1/nodes/register",
            json=node_payload(name=f"node{i}", wireguard_public_key=f"key{i}=="),
        )

    response = await client.get(
        "/api/v1/nodes/",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert response.status_code == 200
    assert len(response.json()) == 3


async def test_list_nodes_requires_admin(client: AsyncClient):
    response = await client.get(
        "/api/v1/nodes/",
        headers={"Authorization": "Bearer wrong"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


async def test_health_no_auth(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert isinstance(data["node_count"], int)


async def test_health_reflects_node_count(client: AsyncClient):
    for i in range(2):
        await client.post(
            "/api/v1/nodes/register",
            json=node_payload(name=f"node{i}", wireguard_public_key=f"key{i}=="),
        )

    response = await client.get("/health")
    assert response.json()["node_count"] == 2
