import logging

from fastapi import WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Node

logger = logging.getLogger(__name__)


class AgentConnectionManager:
    """Tracks connected agent WebSocket sessions and broadcasts peer updates."""

    def __init__(self) -> None:
        # node_id (str) -> WebSocket
        self._connections: dict[str, WebSocket] = {}

    async def connect(self, node_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._connections[node_id] = ws
        logger.debug("Agent %s connected (%d total)", node_id, len(self._connections))

    def disconnect(self, node_id: str) -> None:
        self._connections.pop(node_id, None)
        logger.debug("Agent %s disconnected (%d remaining)", node_id, len(self._connections))

    async def send_peers(self, node_id: str, session: AsyncSession) -> None:
        """Send the current peer list to a single connected agent."""
        ws = self._connections.get(node_id)
        if not ws:
            return
        try:
            from app.schemas.node import PeerResponse
            from app.services.peer_service import get_peers

            result = await session.execute(select(Node).where(Node.id == node_id))
            node = result.scalar_one_or_none()
            if not node:
                return
            peers = await get_peers(node, session)
            payload = {"peers": [p.model_dump(mode="json") for p in peers]}
            await ws.send_json(payload)
        except Exception as exc:
            # WS is already closed — clean up the stale entry silently
            logger.debug("Peer push to agent %s failed (%s); removing stale connection", node_id, exc)
            self.disconnect(node_id)

    async def broadcast_peers(self, session: AsyncSession) -> None:
        """Send updated peer lists to all connected agents."""
        if not self._connections:
            return
        for node_id in list(self._connections):
            await self.send_peers(node_id, session)


agent_manager = AgentConnectionManager()


async def broadcast_peers(session: AsyncSession) -> None:
    await agent_manager.broadcast_peers(session)
