from app.db.models import DestinationPolicy, Node, TransportStatus


def policy_applies_to_node(policy: DestinationPolicy, node: Node) -> bool:
    if policy.node_id is not None:
        return policy.node_id == node.id
    if policy.site_id is not None:
        return policy.site_id == node.site_id
    return True


def resolve_policy_for_node(node: Node, policy: DestinationPolicy) -> dict:
    links_by_kind = {
        link.kind: link
        for link in getattr(node, "transport_links", [])
        if link.admin_state_up and link.interface_name and link.overlay_vpn_ip
    }
    selected = None
    resolution = "unavailable"
    preferred = links_by_kind.get(policy.preferred_transport)
    if preferred is not None and preferred.status != TransportStatus.DOWN:
        selected = preferred
        resolution = "preferred"
    elif policy.fallback_transport is not None:
        fallback = links_by_kind.get(policy.fallback_transport)
        if fallback is not None and fallback.status != TransportStatus.DOWN:
            selected = fallback
            resolution = "fallback"

    return {
        "policy": policy,
        "selected": selected,
        "resolution": resolution,
    }
