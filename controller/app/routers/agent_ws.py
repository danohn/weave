import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent_ws import agent_manager
from app.db.base import AsyncSessionLocal
from app.db.models import Node, NodeStatus

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/api/v1/nodes/{node_id}/ws")
async def agent_ws(websocket: WebSocket, node_id: str) -> None:
    """
    Persistent WebSocket connection for edge node agents.

    Agents connect here to receive real-time peer list updates instead of
    polling GET /peers.  Authentication uses the node bearer token passed
    in the Authorization header (Bearer <token>) to avoid it appearing in
    proxy access logs.
    """
    auth_header = websocket.headers.get("authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()

    async with AsyncSessionLocal() as session:
        # Validate token and node ownership
        result = await session.execute(
            select(Node).where(Node.auth_token == token)
        )
        node = result.scalar_one_or_none()

        if not node or str(node.id) != node_id or node.status == NodeStatus.REVOKED:
            await websocket.close(code=4001)
            return

        await agent_manager.connect(node_id, websocket)
        try:
            # Push current peer list immediately on connect
            await agent_manager.send_peers(node_id, session)

            # Hold the connection open; agents may send pings as keepalives
            while True:
                await websocket.receive_text()

        except WebSocketDisconnect:
            pass
        finally:
            agent_manager.disconnect(node_id)
