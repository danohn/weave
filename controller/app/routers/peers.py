from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_node
from app.db.base import get_session
from app.db.models import Node
from app.schemas.node import PeerResponse
from app.services import peer_service

router = APIRouter(prefix="/api/v1/nodes", tags=["peers"])


@router.get("/{node_id}/peers", response_model=list[PeerResponse])
async def get_peers(
    node_id: str,
    current_node: Node = Depends(get_current_node),
    session: AsyncSession = Depends(get_session),
) -> list[PeerResponse]:
    if str(current_node.id) != node_id:
        raise HTTPException(status_code=403, detail="Token does not match node")
    return await peer_service.get_peers(current_node, session)
