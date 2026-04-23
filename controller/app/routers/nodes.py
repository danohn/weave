from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent_ws import broadcast_peers
from app.core.security import get_current_node, require_admin
from app.core.websocket import broadcast_state
from app.db.base import get_session
from app.db.models import Node, NodeStatus
from app.schemas.node import (
    build_node_admin_response,
    HeartbeatRequest,
    HeartbeatResponse,
    NodeAdminResponse,
    NodeRegisterRequest,
    NodeRegisterResponse,
    NodeTokenRotateResponse,
    NodeUpdateRequest,
    OverlayConfigResponse,
)
from app.services import (
    event_service,
    frr_service,
    node_service,
    peer_service,
    policy_service,
    wireguard_service,
)

router = APIRouter(prefix="/api/v1/nodes", tags=["nodes"])


async def _build_admin_response(session: AsyncSession, node: Node) -> NodeAdminResponse:
    bgp = await frr_service.get_bgp_status()
    policies = await policy_service.list_policies(session)
    event_map = await event_service.list_recent_events_by_node(
        session, node_ids=[node.id]
    )
    return build_node_admin_response(
        node, bgp=bgp, policies=policies, events=event_map.get(node.id, [])
    )


async def _build_admin_responses(
    session: AsyncSession, nodes: list[Node]
) -> list[NodeAdminResponse]:
    bgp = await frr_service.get_bgp_status()
    policies = await policy_service.list_policies(session)
    event_map = await event_service.list_recent_events_by_node(
        session, node_ids=[node.id for node in nodes]
    )
    return [
        build_node_admin_response(
            node, bgp=bgp, policies=policies, events=event_map.get(node.id, [])
        )
        for node in nodes
    ]


def _transport_signature(node: Node) -> tuple[tuple[str | None, ...], ...]:
    links = []
    for link in getattr(node, "transport_links", []):
        links.append(
            (
                link.kind.value if link.kind is not None else None,
                link.name,
                link.interface_name,
                link.wireguard_public_key,
                link.overlay_vpn_ip,
                link.endpoint_ip,
                str(link.endpoint_port) if link.endpoint_port is not None else None,
            )
        )
    return tuple(sorted(links))


async def _on_node_activated(node: Node) -> None:
    """Add the node to the controller's WireGuard, BFD, and BGP config."""
    links = sorted(
        [
            link
            for link in getattr(node, "transport_links", [])
            if link.wireguard_public_key and link.overlay_vpn_ip
        ],
        key=lambda item: (item.priority, item.kind.value),
    )
    if not links:
        await wireguard_service.add_peer(node)
        return
    for link in links:
        await wireguard_service.add_transport_peer(
            link, node_name=node.name, site_subnet=node.site_subnet
        )
        await frr_service.add_bfd_peer(link, node.name)
        await frr_service.add_neighbor(link, node.name)


async def _on_node_removed(node: Node) -> None:
    """Remove the node from the controller's WireGuard, BFD, and BGP config."""
    links = sorted(
        [
            link
            for link in getattr(node, "transport_links", [])
            if link.wireguard_public_key and link.overlay_vpn_ip
        ],
        key=lambda item: (item.priority, item.kind.value),
    )
    if not links:
        await wireguard_service.remove_peer(node)
        return
    for link in links:
        await wireguard_service.remove_transport_peer(link, node_name=node.name)
        await frr_service.remove_neighbor(link, node.name)
        await frr_service.remove_bfd_peer(link, node.name)


@router.post("/register", response_model=NodeRegisterResponse, status_code=201)
async def register(
    data: NodeRegisterRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> NodeRegisterResponse:
    node, auth_token = await node_service.register_node(request, data, session)
    await broadcast_state(session)
    await broadcast_peers(session)
    if node.status == NodeStatus.ACTIVE:
        await _on_node_activated(node)
    return NodeRegisterResponse(
        id=node.id,
        auth_token=auth_token,
        vpn_ip=node.vpn_ip,
        device_claim_id=node.device_claim_id,
    )


@router.post("/{node_id}/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(
    node_id: str,
    request: Request,
    data: HeartbeatRequest | None = None,
    current_node: Node = Depends(get_current_node),
    session: AsyncSession = Depends(get_session),
) -> HeartbeatResponse:
    if str(current_node.id) != node_id:
        raise HTTPException(status_code=403, detail="Token does not match node")
    if current_node.status == NodeStatus.REVOKED:
        raise HTTPException(status_code=403, detail="Node is revoked")
    prior_node = await node_service.get_node_by_id(session, current_node.id)
    prior_signature = _transport_signature(prior_node) if prior_node is not None else ()
    was_offline = current_node.status == NodeStatus.OFFLINE
    node = await node_service.update_heartbeat(
        current_node,
        request,
        session,
        transport_links=[
            item.model_dump(mode="json")
            for item in (data.transport_links if data else [])
        ],
    )
    await broadcast_state(session)
    await broadcast_peers(session)
    transport_changed = _transport_signature(node) != prior_signature
    # Update the WG peer endpoint when a node recovers from OFFLINE — its
    # reflected IP may have changed while it was unreachable.
    if node.status == NodeStatus.ACTIVE and (was_offline or transport_changed):
        await _on_node_activated(node)
    return HeartbeatResponse(status=node.status, last_seen=node.last_seen)


@router.post("/{node_id}/offline", status_code=204)
async def go_offline(
    node_id: str,
    current_node: Node = Depends(get_current_node),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Called by the agent on clean shutdown to immediately mark itself OFFLINE."""
    if str(current_node.id) != node_id:
        raise HTTPException(status_code=403, detail="Token does not match node")
    if current_node.status == NodeStatus.ACTIVE:
        node = await node_service.get_node_by_id(session, current_node.id)
        if node is None:
            raise HTTPException(status_code=404, detail="Node not found")
        await node_service.mark_node_offline(node, session)
        for link in node.transport_links:
            await frr_service.remove_neighbor(link, node.name)
        await broadcast_state(session)
        await broadcast_peers(session)


@router.post("/{node_id}/rotate-token", response_model=NodeTokenRotateResponse)
async def rotate_token(
    node_id: str,
    current_node: Node = Depends(get_current_node),
    session: AsyncSession = Depends(get_session),
) -> NodeTokenRotateResponse:
    if str(current_node.id) != node_id:
        raise HTTPException(status_code=403, detail="Token does not match node")
    if current_node.status == NodeStatus.REVOKED:
        raise HTTPException(status_code=403, detail="Node is revoked")
    auth_token = await node_service.rotate_node_token(current_node, session)
    return NodeTokenRotateResponse(auth_token=auth_token)


@router.get("/{node_id}/frr-config", response_class=PlainTextResponse)
async def frr_config(
    node_id: str,
    current_node: Node = Depends(get_current_node),
    session: AsyncSession = Depends(get_session),
) -> str:
    """Return the FRR BGP config for this node as plain text.

    The agent writes this verbatim to /etc/frr/frr.conf and reloads FRR.
    """
    if str(current_node.id) != node_id:
        raise HTTPException(status_code=403, detail="Token does not match node")
    node = await node_service.get_node_by_id(session, current_node.id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    return frr_service.generate_node_config(node)


@router.get("/{node_id}/overlay-config", response_model=OverlayConfigResponse)
async def overlay_config(
    node_id: str,
    current_node: Node = Depends(get_current_node),
    session: AsyncSession = Depends(get_session),
) -> OverlayConfigResponse:
    if str(current_node.id) != node_id:
        raise HTTPException(status_code=403, detail="Token does not match node")
    node = await node_service.get_node_by_id(session, current_node.id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    return await peer_service.get_overlay_config(node, session)


@router.patch("/{node_id}", response_model=NodeAdminResponse)
async def update_node(
    node_id: str,
    data: NodeUpdateRequest,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_admin),
) -> NodeAdminResponse:
    """Update editable node fields (currently: site_subnet)."""
    node = await node_service.update_node(node_id, data, session)
    if node.status in (NodeStatus.ACTIVE, NodeStatus.OFFLINE):
        await _on_node_activated(node)
    await broadcast_peers(session)
    await broadcast_state(session)
    return await _build_admin_response(session, node)


@router.patch("/{node_id}/activate", response_model=NodeAdminResponse)
async def activate(
    node_id: str,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_admin),
) -> NodeAdminResponse:
    node = await node_service.activate_node(node_id, session)
    await broadcast_state(session)
    await broadcast_peers(session)
    await _on_node_activated(node)
    return await _build_admin_response(session, node)


@router.delete("/{node_id}/revoke", response_model=NodeAdminResponse)
async def revoke(
    node_id: str,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_admin),
) -> NodeAdminResponse:
    node = await node_service.revoke_node(node_id, session)
    await broadcast_state(session)
    await broadcast_peers(session)
    await _on_node_removed(node)
    return await _build_admin_response(session, node)


@router.delete("/{node_id}", status_code=204)
async def delete(
    node_id: str,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_admin),
) -> None:
    # Fetch node before deletion so we have its WG key and VPN IP
    from sqlalchemy import select

    result = await session.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if node:
        await _on_node_removed(node)
    await node_service.delete_node(node_id, session)
    await broadcast_state(session)
    await broadcast_peers(session)


@router.get("/", response_model=list[NodeAdminResponse])
async def list_nodes(
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_admin),
) -> list[NodeAdminResponse]:
    nodes = await node_service.list_all_nodes(session)
    return await _build_admin_responses(session, nodes)
