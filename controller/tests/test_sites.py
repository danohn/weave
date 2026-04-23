from httpx import AsyncClient

ADMIN_TOKEN = "test-admin-token"


def node_payload(**overrides) -> dict:
    defaults = {
        "name": "branch-sydney",
        "wireguard_public_key": "abc123pubkey==",
        "endpoint_ip": "1.2.3.4",
        "endpoint_port": 51820,
    }
    return {**defaults, **overrides}


async def test_register_creates_site_and_default_transport(client: AsyncClient):
    reg = await client.post("/api/v1/nodes/register", json=node_payload())
    assert reg.status_code == 201
    node_id = reg.json()["id"]

    resp = await client.get(
        "/api/v1/nodes/",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200
    node = next(item for item in resp.json() if item["id"] == node_id)
    assert node["site"]["name"] == "branch-sydney"
    assert node["site"]["primary_prefix"] is None
    assert node["active_transport"]["name"] == "wan1"
    assert node["active_transport"]["kind"] == "internet"
    assert node["active_transport"]["endpoint_port"] == 51820


async def test_heartbeat_updates_transport_metrics(client: AsyncClient):
    reg = await client.post("/api/v1/nodes/register", json=node_payload())
    assert reg.status_code == 201
    node_id = reg.json()["id"]
    token = reg.json()["auth_token"]

    hb = await client.post(
        f"/api/v1/nodes/{node_id}/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "transport_links": [
                {
                    "name": "mpls-a",
                    "kind": "mpls",
                    "endpoint_port": 51820,
                    "interface_name": "wg0",
                    "rtt_ms": 12,
                    "jitter_ms": 3,
                    "loss_pct": 0,
                }
            ]
        },
    )
    assert hb.status_code == 200

    resp = await client.get(
        "/api/v1/nodes/",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200
    node = next(item for item in resp.json() if item["id"] == node_id)
    assert node["active_transport"]["name"] == "mpls-a"
    assert node["active_transport"]["kind"] == "mpls"
    assert node["active_transport"]["status"] == "HEALTHY"
    assert node["active_transport"]["rtt_ms"] == 12
