import json
import logging

from fastapi import WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        logger.debug("WS client connected (%d total)", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)
        logger.debug("WS client disconnected (%d remaining)", len(self._connections))

    async def broadcast(self, payload: dict) -> None:
        if not self._connections:
            return
        msg = json.dumps(payload, default=str)
        dead: list[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


async def broadcast_state(session: AsyncSession) -> None:
    """Fetch current nodes + claims + BGP and push to all connected WS clients."""
    if not manager._connections:
        return
    # Deferred imports to avoid circular dependencies
    from app.schemas.auth import DeviceClaimResponse
    from app.schemas.node import build_node_admin_response
    from app.services import auth_service, frr_service, node_service

    nodes = await node_service.list_all_nodes(session)
    claims = await auth_service.list_claims(session)
    bgp = await frr_service.get_bgp_status()
    payload = {
        "nodes": [build_node_admin_response(n).model_dump(mode="json") for n in nodes],
        "claims": [DeviceClaimResponse.model_validate(c).model_dump(mode="json") for c in claims],
        "bgp": bgp,
    }
    await manager.broadcast(payload)
