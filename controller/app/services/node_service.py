import ipaddress
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import issue_hashed_token, verify_token
from app.db.models import DeviceClaim, DeviceClaimStatus, Node, NodeStatus
from app.schemas.node import NodeRegisterRequest, NodeUpdateRequest


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
) -> tuple[Node, str]:
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

    claim_token = data.claim_token or data.preauth_token
    claim_row: DeviceClaim | None = None
    if claim_token:
        candidate_result = await session.execute(
            select(DeviceClaim).where(DeviceClaim.token_prefix == claim_token[:8])
        )
        candidates = list(candidate_result.scalars().all())
        claim_row = next(
            (candidate for candidate in candidates if verify_token(claim_token, candidate.token_hash)),
            None,
        )
        if claim_row is None:
            raise HTTPException(status_code=401, detail="Invalid claim token")
        if claim_row.status in {DeviceClaimStatus.CLAIMED, DeviceClaimStatus.ACTIVE}:
            raise HTTPException(status_code=401, detail="Claim token has already been used")
        if claim_row.status == DeviceClaimStatus.REVOKED:
            raise HTTPException(status_code=401, detail="Claim token has been revoked")
        expires_at = claim_row.expires_at
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at and expires_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="Claim token has expired")
        if claim_row.expected_name and claim_row.expected_name != data.name:
            raise HTTPException(status_code=409, detail="Node name does not match the device claim")
        if claim_row.site_subnet and data.site_subnet and claim_row.site_subnet != data.site_subnet:
            raise HTTPException(status_code=409, detail="Site subnet does not match the device claim")
    elif settings.REQUIRE_PREAUTH:
        raise HTTPException(status_code=401, detail="A claim token is required to register")

    vpn_ip = await _allocate_vpn_ip(session)
    reflected_ip = request.client.host if request.client else None
    now = datetime.now(timezone.utc)
    initial_status = NodeStatus.ACTIVE if claim_row else NodeStatus.PENDING
    auth_token, auth_token_prefix, auth_token_hash = issue_hashed_token()
    node = Node(
        name=data.name,
        wireguard_public_key=data.wireguard_public_key,
        endpoint_ip=data.endpoint_ip or reflected_ip,
        endpoint_port=data.endpoint_port,
        vpn_ip=vpn_ip,
        site_subnet=claim_row.site_subnet if claim_row and claim_row.site_subnet else data.site_subnet,
        reflected_endpoint_ip=reflected_ip,
        auth_token_hash=auth_token_hash,
        auth_token_prefix=auth_token_prefix,
        auth_token_issued_at=now,
        device_claim_id=claim_row.id if claim_row else None,
        status=initial_status,
        last_seen=now,
        created_at=now,
    )
    session.add(node)
    await session.flush()

    if claim_row:
        claim_row.claimed_at = now
        claim_row.claimed_by_node_id = node.id
        claim_row.status = (
            DeviceClaimStatus.ACTIVE if initial_status == NodeStatus.ACTIVE else DeviceClaimStatus.CLAIMED
        )

    await session.commit()
    await session.refresh(node)
    return node, auth_token


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


async def expire_stale_nodes(session: AsyncSession, threshold_seconds: int) -> list[Node]:
    """Set ACTIVE nodes to OFFLINE when last_seen is older than threshold_seconds.

    Returns the list of nodes transitioned so callers can clean up data-plane state.
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
    return stale


async def mark_node_offline(node: Node, session: AsyncSession) -> Node:
    """Immediately mark a node OFFLINE (called on clean agent shutdown)."""
    node.status = NodeStatus.OFFLINE
    await session.commit()
    await session.refresh(node)
    return node


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
    if node.device_claim_id:
        claim_result = await session.execute(
            select(DeviceClaim).where(DeviceClaim.id == node.device_claim_id)
        )
        claim = claim_result.scalar_one_or_none()
        if claim and claim.status != DeviceClaimStatus.REVOKED:
            claim.status = DeviceClaimStatus.ACTIVE
    await session.commit()
    await session.refresh(node)
    return node


async def revoke_node(node_id: str, session: AsyncSession) -> Node:
    result = await session.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    node.status = NodeStatus.REVOKED
    if node.device_claim_id:
        claim_result = await session.execute(
            select(DeviceClaim).where(DeviceClaim.id == node.device_claim_id)
        )
        claim = claim_result.scalar_one_or_none()
        if claim:
            claim.status = DeviceClaimStatus.REVOKED
    await session.commit()
    await session.refresh(node)
    return node


async def delete_node(node_id: str, session: AsyncSession) -> None:
    result = await session.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    claim_result = await session.execute(
        select(DeviceClaim).where(DeviceClaim.claimed_by_node_id == node_id)
    )
    for claim in claim_result.scalars().all():
        claim.claimed_by_node_id = None
        if claim.status != DeviceClaimStatus.REVOKED:
            claim.status = DeviceClaimStatus.CLAIMED
    await session.delete(node)
    await session.commit()


async def update_node(node_id: str, data: NodeUpdateRequest, session: AsyncSession) -> Node:
    result = await session.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    node.site_subnet = data.site_subnet
    await session.commit()
    await session.refresh(node)
    return node


async def list_all_nodes(session: AsyncSession) -> list[Node]:
    result = await session.execute(select(Node))
    return list(result.scalars().all())


async def rotate_node_token(node: Node, session: AsyncSession) -> str:
    plaintext, prefix, token_hash = issue_hashed_token()
    node.auth_token_prefix = prefix
    node.auth_token_hash = token_hash
    node.auth_token_issued_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(node)
    return plaintext
