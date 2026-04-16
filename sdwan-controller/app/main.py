import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.base import AsyncSessionLocal, Base, engine, get_session
from app.db.models import Node
from app.routers import nodes, peers
from app.services import node_service

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
    title="SD-WAN Controller",
    description=(
        "WireGuard-based SD-WAN control plane — analogous to Cisco Viptela's "
        "vBond (orchestration) and vSmart (policy/peer distribution) components."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(nodes.router)
app.include_router(peers.router)


@app.get("/health", tags=["health"])
async def health(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    result = await session.execute(select(func.count()).select_from(Node))
    node_count = result.scalar_one()
    return {"status": "ok", "node_count": node_count}
