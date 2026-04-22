import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.agent_ws import agent_manager
from app.core.security import find_node_for_token
from app.db.base import AsyncSessionLocal
from app.db.models import NodeStatus

logger = logging.getLogger(__name__)

router = APIRouter()

PING_INTERVAL = 10  # seconds between keepalive pings
PING_TIMEOUT  = 10  # seconds to wait for a pong before declaring the agent dead


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
        node = await find_node_for_token(session, token)

        if not node or str(node.id) != node_id or node.status == NodeStatus.REVOKED:
            await websocket.close(code=4001)
            return

        await agent_manager.connect(node_id, websocket)
        logger.info("Agent %s connected", node_id)
        try:
            # Push current peer list immediately on connect
            await agent_manager.send_peers(node_id, session)

            # Keepalive loop: ping the agent every PING_INTERVAL seconds.
            # TCP alone won't detect a dead connection when a cable is unplugged
            # (no RST is sent). By waiting for a pong with a timeout we detect
            # it within PING_INTERVAL + PING_TIMEOUT seconds.
            while True:
                await asyncio.sleep(PING_INTERVAL)
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break  # send failed — connection already gone
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=PING_TIMEOUT)
                except asyncio.TimeoutError:
                    logger.info("Agent %s ping timeout — declaring offline", node_id)
                    break

        except WebSocketDisconnect:
            pass
        finally:
            agent_manager.disconnect(node_id)
            logger.info(
                "Agent %s peer stream disconnected; keeping status unchanged until heartbeat expiry or clean shutdown",
                node_id,
            )
