import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.websocket import broadcast_state, manager
from app.db.base import AsyncSessionLocal

router = APIRouter(tags=["ws"])


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    user = ws.session.get("user")
    if not user:
        await ws.close(code=4001, reason="Unauthorized")
        return

    await manager.connect(ws)
    try:
        # Push current state immediately so the client doesn't wait for a mutation
        async with AsyncSessionLocal() as session:
            await broadcast_state(session)
        # Hold the connection open; we don't expect messages from the client
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws)
