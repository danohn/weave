import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    force=True,
)

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import settings
from app.core.agent_ws import broadcast_peers
from app.core.websocket import broadcast_state
from app.db.base import AsyncSessionLocal, Base, engine, get_session
from app.db.models import Node, NodeStatus, Site, TransportLink
from app.routers import agent_ws, auth, auth_web, bgp, nodes, peers, policies, ws
from app.services import frr_service, node_service, wireguard_service

logger = logging.getLogger(__name__)


async def _expiry_loop() -> None:
    """Background task: periodically mark stale ACTIVE nodes as OFFLINE."""
    while True:
        await asyncio.sleep(settings.STALE_CHECK_INTERVAL)
        try:
            async with AsyncSessionLocal() as session:
                stale = await node_service.expire_stale_nodes(
                    session, settings.STALE_THRESHOLD_SECONDS
                )
                if stale:
                    logger.info("Marked %d node(s) OFFLINE (no heartbeat)", len(stale))
                    for node in stale:
                        for link in node.transport_links:
                            await frr_service.remove_neighbor(link, node.name)
                    await broadcast_state(session)
                    await broadcast_peers(session)
        except Exception:
            logger.exception("Error in expiry loop")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Restore WireGuard peers and BGP neighbors for all known nodes after a
    # container restart. OFFLINE nodes are kept in WG/FRR so sessions recover
    # automatically when they come back; revoked/pending nodes are excluded.
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Node)
            .options(
                selectinload(Node.transport_links),
                selectinload(Node.site).selectinload(Site.prefixes),
            )
            .where(
                Node.status.in_([NodeStatus.ACTIVE, NodeStatus.OFFLINE])
            )
        )
        existing_nodes = list(result.scalars().all())

    if existing_nodes:
        logger.info("Syncing %d node(s) to WireGuard and FRR on startup", len(existing_nodes))
        await wireguard_service.sync_peers(existing_nodes)
        for node in existing_nodes:
            for link in sorted(
                [item for item in node.transport_links if item.wireguard_public_key and item.overlay_vpn_ip],
                key=lambda item: (item.priority, item.kind.value),
            ):
                await frr_service.add_bfd_peer(link, node.name)
                await frr_service.add_neighbor(link, node.name)

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
    SessionMiddleware,
    secret_key=settings.SESSION_SECRET,
    session_cookie="weave_session",
    same_site="lax",
    https_only=settings.session_cookie_secure,
    max_age=86400 * 7,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agent_ws.router)
app.include_router(auth.router)
app.include_router(auth_web.router)
app.include_router(bgp.router)
app.include_router(nodes.router)
app.include_router(peers.router)
app.include_router(policies.router)
app.include_router(ws.router)


@app.get("/health", tags=["health"])
async def health(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    result = await session.execute(select(func.count()).select_from(Node))
    node_count = result.scalar_one()
    return {"status": "ok", "node_count": node_count}
