from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent_ws import broadcast_peers
from app.core.security import get_current_node, require_admin
from app.core.websocket import broadcast_state
from app.db.base import get_session
from app.db.models import Node, NodeStatus
from app.schemas.node import (
    HeartbeatResponse,
    NodeAdminResponse,
    NodeRegisterRequest,
    NodeRegisterResponse,
)
from app.services import frr_service, node_service, wireguard_service

router = APIRouter(prefix="/api/v1/nodes", tags=["nodes"])


async def _on_node_activated(node: Node) -> None:
    """Add the node to the controller's WireGuard and BGP config."""
    await wireguard_service.add_peer(node)
    await frr_service.add_neighbor(node)


async def _on_node_removed(node: Node) -> None:
    """Remove the node from the controller's WireGuard and BGP config."""
    await wireguard_service.remove_peer(node)
    await frr_service.remove_neighbor(node)


@router.post("/register", response_model=NodeRegisterResponse, status_code=201)
async def register(
    data: NodeRegisterRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> NodeRegisterResponse:
    node = await node_service.register_node(request, data, session)
    await broadcast_state(session)
    await broadcast_peers(session)
    if node.status == NodeStatus.ACTIVE:
        await _on_node_activated(node)
    return NodeRegisterResponse(
        id=node.id, auth_token=node.auth_token, vpn_ip=node.vpn_ip
    )


@router.post("/{node_id}/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(
    node_id: str,
    request: Request,
    current_node: Node = Depends(get_current_node),
    session: AsyncSession = Depends(get_session),
) -> HeartbeatResponse:
    if str(current_node.id) != node_id:
        raise HTTPException(status_code=403, detail="Token does not match node")
    if current_node.status == NodeStatus.REVOKED:
        raise HTTPException(status_code=403, detail="Node is revoked")
    was_offline = current_node.status == NodeStatus.OFFLINE
    node = await node_service.update_heartbeat(current_node, request, session)
    await broadcast_state(session)
    await broadcast_peers(session)
    # Update the WG peer endpoint when a node recovers from OFFLINE — its
    # reflected IP may have changed while it was unreachable.
    if was_offline and node.status == NodeStatus.ACTIVE:
        await wireguard_service.add_peer(node)
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
        await node_service.mark_node_offline(current_node, session)
        await broadcast_state(session)
        await broadcast_peers(session)


@router.get("/{node_id}/frr-config")
async def frr_config(
    node_id: str,
    current_node: Node = Depends(get_current_node),
) -> str:
    """Return the FRR BGP config for this node as plain text.

    The agent writes this verbatim to /etc/frr/frr.conf and reloads FRR.
    """
    if str(current_node.id) != node_id:
        raise HTTPException(status_code=403, detail="Token does not match node")
    return frr_service.generate_node_config(current_node)


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
    return NodeAdminResponse.model_validate(node)


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
    return NodeAdminResponse.model_validate(node)


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
    return [NodeAdminResponse.model_validate(n) for n in nodes]
