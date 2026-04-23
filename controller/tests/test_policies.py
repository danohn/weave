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


async def test_create_policy_and_resolve_overlay_config(client: AsyncClient):
    reg = await client.post(
        "/api/v1/nodes/register", json=node_payload(name="branch-perth")
    )
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
                    "wireguard_public_key": "mpls-pubkey==",
                    "endpoint_port": 51821,
                    "interface_name": "weave-mpls",
                    "rtt_ms": 12,
                    "jitter_ms": 1,
                    "loss_pct": 0,
                }
            ]
        },
    )
    assert hb.status_code == 200

    policy = await client.post(
        "/api/v1/policies/",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        json={
            "name": "pbx-over-mpls",
            "destination_prefix": "10.50.0.0/24",
            "preferred_transport": "mpls",
            "fallback_transport": "internet",
            "priority": 10,
            "enabled": True,
        },
    )
    assert policy.status_code == 201

    overlay = await client.get(
        f"/api/v1/nodes/{node_id}/overlay-config",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert overlay.status_code == 200
    policies = overlay.json()["destination_policies"]
    assert len(policies) == 1
    assert policies[0]["destination_prefix"] == "10.50.0.0/24"
    assert policies[0]["selected_transport"] == "mpls"
    assert policies[0]["selected_interface"] == "weave-mpls"


async def test_policy_falls_back_when_preferred_transport_down(client: AsyncClient):
    reg = await client.post(
        "/api/v1/nodes/register", json=node_payload(name="branch-paris")
    )
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
                    "wireguard_public_key": "mpls-down-pubkey==",
                    "endpoint_port": 51821,
                    "interface_name": "weave-mpls",
                    "loss_pct": 100,
                }
            ]
        },
    )
    assert hb.status_code == 200

    policy = await client.post(
        "/api/v1/policies/",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        json={
            "name": "pbx-fallback-internet",
            "destination_prefix": "10.60.0.0/24",
            "preferred_transport": "mpls",
            "fallback_transport": "internet",
            "priority": 10,
            "enabled": True,
        },
    )
    assert policy.status_code == 201

    overlay = await client.get(
        f"/api/v1/nodes/{node_id}/overlay-config",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert overlay.status_code == 200
    policies = overlay.json()["destination_policies"]
    assert len(policies) == 1
    assert policies[0]["selected_transport"] == "internet"
    assert policies[0]["selected_interface"] == "weave-internet"


async def test_site_scoped_policy_only_applies_to_matching_site(client: AsyncClient):
    reg_a = await client.post(
        "/api/v1/nodes/register",
        json=node_payload(name="alpha", site_subnet="10.1.0.0/24"),
    )
    reg_b = await client.post(
        "/api/v1/nodes/register",
        json=node_payload(
            name="beta",
            wireguard_public_key="beta-pubkey==",
            endpoint_ip="2.2.2.2",
            site_subnet="10.2.0.0/24",
        ),
    )
    assert reg_a.status_code == 201
    assert reg_b.status_code == 201

    nodes = await client.get(
        "/api/v1/nodes/", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"}
    )
    assert nodes.status_code == 200
    alpha = next(item for item in nodes.json() if item["id"] == reg_a.json()["id"])
    beta = next(item for item in nodes.json() if item["id"] == reg_b.json()["id"])

    policy = await client.post(
        "/api/v1/policies/",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        json={
            "name": "alpha-pbx",
            "destination_prefix": "10.70.0.0/24",
            "site_id": alpha["site"]["id"],
            "preferred_transport": "internet",
            "priority": 10,
            "enabled": True,
        },
    )
    assert policy.status_code == 201

    alpha_overlay = await client.get(
        f"/api/v1/nodes/{alpha['id']}/overlay-config",
        headers={"Authorization": f"Bearer {reg_a.json()['auth_token']}"},
    )
    beta_overlay = await client.get(
        f"/api/v1/nodes/{beta['id']}/overlay-config",
        headers={"Authorization": f"Bearer {reg_b.json()['auth_token']}"},
    )
    assert alpha_overlay.status_code == 200
    assert beta_overlay.status_code == 200
    assert len(alpha_overlay.json()["destination_policies"]) == 1
    assert len(beta_overlay.json()["destination_policies"]) == 0


async def test_node_scoped_policy_only_applies_to_matching_node(client: AsyncClient):
    reg_a = await client.post("/api/v1/nodes/register", json=node_payload(name="gamma"))
    reg_b = await client.post(
        "/api/v1/nodes/register",
        json=node_payload(
            name="delta", wireguard_public_key="delta-pubkey==", endpoint_ip="3.3.3.3"
        ),
    )
    assert reg_a.status_code == 201
    assert reg_b.status_code == 201

    policy = await client.post(
        "/api/v1/policies/",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        json={
            "name": "gamma-only",
            "destination_prefix": "10.80.0.0/24",
            "node_id": reg_a.json()["id"],
            "preferred_transport": "internet",
            "priority": 10,
            "enabled": True,
        },
    )
    assert policy.status_code == 201

    gamma_overlay = await client.get(
        f"/api/v1/nodes/{reg_a.json()['id']}/overlay-config",
        headers={"Authorization": f"Bearer {reg_a.json()['auth_token']}"},
    )
    delta_overlay = await client.get(
        f"/api/v1/nodes/{reg_b.json()['id']}/overlay-config",
        headers={"Authorization": f"Bearer {reg_b.json()['auth_token']}"},
    )
    assert gamma_overlay.status_code == 200
    assert delta_overlay.status_code == 200
    assert len(gamma_overlay.json()["destination_policies"]) == 1
    assert len(delta_overlay.json()["destination_policies"]) == 0
