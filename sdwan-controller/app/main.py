import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.base import AsyncSessionLocal, Base, engine, get_session
from app.db.models import Node
from app.core.websocket import broadcast_state
from app.routers import auth, nodes, peers, ws
from app.services import node_service

STATIC_DIR = Path(__file__).parent / "static"

logger = logging.getLogger(__name__)


async def _expiry_loop() -> None:
    """Background task: periodically mark stale ACTIVE nodes as OFFLINE."""
    while True:
        await asyncio.sleep(settings.STALE_CHECK_INTERVAL)
        try:
            async with AsyncSessionLocal() as session:
                count = await node_service.expire_stale_nodes(
                    session, settings.STALE_THRESHOLD_SECONDS
                )
                if count:
                    logger.info("Marked %d node(s) OFFLINE (no heartbeat)", count)
                    await broadcast_state(session)
        except Exception:
            logger.exception("Error in expiry loop")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables for development convenience.
    # In production, run: uv run alembic upgrade head
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    task = asyncio.create_task(_expiry_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Weave",
    description="WireGuard-based SD-WAN control plane.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(nodes.router)
app.include_router(peers.router)
app.include_router(ws.router)


@app.get("/", include_in_schema=False)
async def dashboard():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/static/style.css", include_in_schema=False)
async def serve_css():
    return FileResponse(STATIC_DIR / "style.css", media_type="text/css")


@app.get("/static/app.js", include_in_schema=False)
async def serve_js():
    return FileResponse(STATIC_DIR / "app.js", media_type="application/javascript")


@app.get("/health", tags=["health"])
async def health(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    result = await session.execute(select(func.count()).select_from(Node))
    node_count = result.scalar_one()
    return {"status": "ok", "node_count": node_count}
