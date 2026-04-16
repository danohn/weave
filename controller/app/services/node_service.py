import ipaddress
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import generate_token
from app.db.models import Node, NodeStatus, PreAuthToken
from app.schemas.node import NodeRegisterRequest


async def _allocate_vpn_ip(session: AsyncSession) -> str:
    """Return the next unallocated host address from VPN_SUBNET."""
    network = ipaddress.ip_network(settings.VPN_SUBNET, strict=False)
    result = await session.execute(select(Node.vpn_ip))
    used = {row[0] for row in result.all() if row[0]}
    for host in network.hosts():
        ip_str = str(host)
        if ip_str not in used:
            return ip_str
    raise HTTPException(
        status_code=503,
        detail=f"VPN address space exhausted ({settings.VPN_SUBNET})",
    )


async def register_node(
    request: Request,
    data: NodeRegisterRequest,
    session: AsyncSession,
) -> Node:
    name_result = await session.execute(select(Node).where(Node.name == data.name))
    if name_result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Node name already exists")

    key_result = await session.execute(
        select(Node).where(Node.wireguard_public_key == data.wireguard_public_key)
    )
    if key_result.scalar_one_or_none():
        raise HTTPException(
            status_code=409, detail="WireGuard public key already registered"
        )

    # Pre-auth token validation
    preauth_row: PreAuthToken | None = None
    if data.preauth_token:
        token_result = await session.execute(
            select(PreAuthToken).where(PreAuthToken.token == data.preauth_token)
        )
        preauth_row = token_result.scalar_one_or_none()
        if not preauth_row or preauth_row.used_at is not None:
            raise HTTPException(status_code=401, detail="Invalid or already-used pre-auth token")
    elif settings.REQUIRE_PREAUTH:
        raise HTTPException(status_code=401, detail="A pre-auth token is required to register")

    vpn_ip = await _allocate_vpn_ip(session)
    reflected_ip = request.client.host if request.client else None
    now = datetime.now(timezone.utc)
    initial_status = NodeStatus.ACTIVE if preauth_row else NodeStatus.PENDING
    node = Node(
        name=data.name,
        wireguard_public_key=data.wireguard_public_key,
        endpoint_ip=reflected_ip,
        endpoint_port=data.endpoint_port,
        vpn_ip=vpn_ip,
        reflected_endpoint_ip=reflected_ip,
        auth_token=generate_token(),
        status=initial_status,
        last_seen=now,
        created_at=now,
    )
    session.add(node)
    await session.flush()  # populate node.id before updating the token

    if preauth_row:
        preauth_row.used_at = now
        preauth_row.used_by_node_id = node.id

    await session.commit()
    await session.refresh(node)
    return node


async def update_heartbeat(
    node: Node,
    request: Request,
    session: AsyncSession,
) -> Node:
    node.last_seen = datetime.now(timezone.utc)
    if request.client:
        node.reflected_endpoint_ip = request.client.host
    # Auto-recover: an OFFLINE node that heartbeats is back online
    if node.status == NodeStatus.OFFLINE:
        node.status = NodeStatus.ACTIVE
    await session.commit()
    await session.refresh(node)
    return node


async def expire_stale_nodes(session: AsyncSession, threshold_seconds: int) -> int:
    """Set ACTIVE nodes to OFFLINE when last_seen is older than threshold_seconds.

    Returns the number of nodes transitioned.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=threshold_seconds)
    result = await session.execute(
        select(Node).where(
            Node.status == NodeStatus.ACTIVE,
            Node.last_seen < cutoff,
        )
    )
    stale = list(result.scalars().all())
    for node in stale:
        node.status = NodeStatus.OFFLINE
    if stale:
        await session.commit()
    return len(stale)


async def activate_node(node_id: str, session: AsyncSession) -> Node:
    result = await session.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    if node.status != NodeStatus.PENDING:
        raise HTTPException(
            status_code=400, detail="Only PENDING nodes can be activated"
        )
    node.status = NodeStatus.ACTIVE
    await session.commit()
    await session.refresh(node)
    return node


async def revoke_node(node_id: str, session: AsyncSession) -> Node:
    result = await session.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    node.status = NodeStatus.REVOKED
    await session.commit()
    await session.refresh(node)
    return node


async def delete_node(node_id: str, session: AsyncSession) -> None:
    result = await session.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    # Nullify any preauth token FK referencing this node before deletion
    token_result = await session.execute(
        select(PreAuthToken).where(PreAuthToken.used_by_node_id == node_id)
    )
    for token in token_result.scalars().all():
        token.used_by_node_id = None
    await session.delete(node)
    await session.commit()


async def list_all_nodes(session: AsyncSession) -> list[Node]:
    result = await session.execute(select(Node))
    return list(result.scalars().all())
