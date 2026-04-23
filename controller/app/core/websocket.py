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
    from app.schemas.node import SiteEventResponse, build_node_admin_response
    from app.services import auth_service, event_service, frr_service, node_service, policy_service

    nodes = await node_service.list_all_nodes(session)
    claims = await auth_service.list_claims(session)
    bgp = await frr_service.get_bgp_status()
    policies = await policy_service.list_policies(session)
    await event_service.record_bgp_state_transitions(session, nodes=nodes, bgp=bgp)
    event_map = await event_service.list_recent_events_by_node(session, node_ids=[node.id for node in nodes])
    events = await event_service.list_recent_events(session, limit=40)
    payload = {
        "nodes": [
            build_node_admin_response(n, bgp=bgp, policies=policies, events=event_map.get(n.id, [])).model_dump(mode="json")
            for n in nodes
        ],
        "claims": [DeviceClaimResponse.model_validate(c).model_dump(mode="json") for c in claims],
        "bgp": bgp,
        "events": [SiteEventResponse.model_validate(item).model_dump(mode="json") for item in events],
        "policies": [
            {
                "id": p.id,
                "name": p.name,
                "destination_prefix": p.destination_prefix,
                "description": p.description,
                "site_id": p.site_id,
                "site_name": p.site.name if getattr(p, "site", None) is not None else None,
                "node_id": p.node_id,
                "node_name": p.node.name if getattr(p, "node", None) is not None else None,
                "preferred_transport": p.preferred_transport,
                "fallback_transport": p.fallback_transport,
                "priority": p.priority,
                "enabled": p.enabled,
            }
            for p in policies
        ],
    }
    await manager.broadcast(payload)
