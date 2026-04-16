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
from app.services import node_service

router = APIRouter(prefix="/api/v1/nodes", tags=["nodes"])


@router.post("/register", response_model=NodeRegisterResponse, status_code=201)
async def register(
    data: NodeRegisterRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> NodeRegisterResponse:
    node = await node_service.register_node(request, data, session)
    await broadcast_state(session)
    await broadcast_peers(session)
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
    node = await node_service.update_heartbeat(current_node, request, session)
    await broadcast_state(session)
    await broadcast_peers(session)
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


@router.patch("/{node_id}/activate", response_model=NodeAdminResponse)
async def activate(
    node_id: str,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_admin),
) -> NodeAdminResponse:
    node = await node_service.activate_node(node_id, session)
    await broadcast_state(session)
    await broadcast_peers(session)
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
    return NodeAdminResponse.model_validate(node)


@router.delete("/{node_id}", status_code=204)
async def delete(
    node_id: str,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_admin),
) -> None:
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
