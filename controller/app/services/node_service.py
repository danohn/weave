import ipaddress
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.core.config import (
    controller_overlay_ip_for_kind,
    settings,
    transport_overlay_subnets,
)
from app.core.security import issue_hashed_token, verify_token
from app.db.models import (
    DeviceClaim,
    DeviceClaimStatus,
    EventKind,
    EventSeverity,
    Node,
    NodeStatus,
    Site,
    SitePrefix,
    TransportKind,
    TransportLink,
    TransportStatus,
)
from app.schemas.node import NodeRegisterRequest, NodeUpdateRequest
from app.services import event_service
from app.services import policy_service
from app.services.policy_resolver import policy_applies_to_node, resolve_policy_for_node

MAX_VPN_IP_ALLOCATION_RETRIES = 3


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


async def _allocate_transport_overlay_ip(
    session: AsyncSession, kind: TransportKind
) -> str:
    subnets = transport_overlay_subnets()
    subnet = subnets.get(kind.value, subnets["other"])
    network = ipaddress.ip_network(subnet, strict=False)
    result = await session.execute(select(TransportLink.overlay_vpn_ip))
    used = {
        row[0]
        for row in result.all()
        if row[0] and ipaddress.ip_address(row[0]) in network
    }
    controller_ip = controller_overlay_ip_for_kind(
        kind.value if kind.value in subnets else "other"
    )
    for host in network.hosts():
        ip_str = str(host)
        if ip_str == controller_ip:
            continue
        if ip_str not in used:
            return ip_str
    raise HTTPException(
        status_code=503,
        detail=f"Transport address space exhausted for {kind.value} ({subnet})",
    )


def _is_vpn_ip_unique_violation(exc: IntegrityError) -> bool:
    message = str(exc.orig).lower() if exc.orig is not None else str(exc).lower()
    return "vpn_ip" in message and ("unique" in message or "duplicate" in message)


def _normalize_site_name(name: str | None, fallback: str) -> str:
    candidate = (name or "").strip()
    return candidate or fallback


async def _get_or_create_site(
    session: AsyncSession,
    *,
    site_name: str,
) -> Site:
    result = await session.execute(select(Site).where(Site.name == site_name))
    site = result.scalar_one_or_none()
    if site is not None:
        return site
    site = Site(name=site_name)
    session.add(site)
    await session.flush()
    return site


async def _upsert_primary_site_prefix(
    session: AsyncSession,
    *,
    site: Site,
    prefix: str | None,
) -> SitePrefix | None:
    result = await session.execute(
        select(SitePrefix)
        .where(SitePrefix.site_id == site.id)
        .order_by(SitePrefix.priority, SitePrefix.created_at)
    )
    existing = result.scalars().first()
    normalized = prefix.strip() if prefix else None
    if normalized is None:
        if existing is not None:
            await session.delete(existing)
        return None
    if existing is None:
        created = SitePrefix(
            site_id=site.id, prefix=normalized, advertise=True, priority=100
        )
        session.add(created)
        await session.flush()
        return created
    existing.prefix = normalized
    existing.advertise = True
    return existing


async def _create_default_transport_link(
    session: AsyncSession,
    *,
    node: Node,
    endpoint_ip: str | None,
    endpoint_port: int,
    reflected_endpoint_ip: str | None,
    wireguard_public_key: str | None = None,
    overlay_vpn_ip: str | None = None,
) -> TransportLink:
    assigned_overlay_ip = overlay_vpn_ip or await _allocate_transport_overlay_ip(
        session, TransportKind.INTERNET
    )
    link = TransportLink(
        node_id=node.id,
        name="wan1",
        kind=TransportKind.INTERNET,
        wireguard_public_key=wireguard_public_key or node.wireguard_public_key,
        overlay_vpn_ip=assigned_overlay_ip,
        controller_vpn_ip=controller_overlay_ip_for_kind(TransportKind.INTERNET.value),
        endpoint_ip=endpoint_ip,
        endpoint_port=endpoint_port,
        reflected_endpoint_ip=reflected_endpoint_ip,
        status=TransportStatus.UNKNOWN,
        is_active=True,
        priority=100,
        interface_name="weave-internet",
    )
    session.add(link)
    await session.flush()
    return link


def _interface_name_for_kind(kind: TransportKind) -> str:
    return f"weave-{kind.value}"


def _priority_for_kind(kind: TransportKind) -> int:
    priorities = {
        TransportKind.MPLS: 50,
        TransportKind.INTERNET: 100,
        TransportKind.LTE: 200,
        TransportKind.OTHER: 300,
    }
    return priorities.get(kind, 300)


async def _upsert_transport_link_report(
    session: AsyncSession,
    *,
    node: Node,
    report: dict,
    reflected_endpoint_ip: str | None,
    reported_at: datetime,
) -> TransportLink:
    kind_raw = report.get("kind")
    try:
        kind = TransportKind(kind_raw) if kind_raw else TransportKind.INTERNET
    except ValueError:
        kind = TransportKind.OTHER
    name = report.get("name") or (
        "wan1" if kind == TransportKind.INTERNET else kind.value
    )
    result = await session.execute(
        select(TransportLink).where(
            TransportLink.node_id == node.id, TransportLink.kind == kind
        )
    )
    link = result.scalar_one_or_none()
    if link is None:
        link = TransportLink(
            node_id=node.id,
            name=name,
            kind=kind,
            priority=_priority_for_kind(kind),
            interface_name=report.get("interface_name")
            or _interface_name_for_kind(kind),
            overlay_vpn_ip=await _allocate_transport_overlay_ip(session, kind),
            controller_vpn_ip=controller_overlay_ip_for_kind(kind.value),
            status=TransportStatus.UNKNOWN,
            is_active=False,
        )
        session.add(link)
        await session.flush()

    link.name = name
    link.interface_name = (
        report.get("interface_name")
        or link.interface_name
        or _interface_name_for_kind(kind)
    )
    link.endpoint_ip = report.get("endpoint_ip") or link.endpoint_ip or node.endpoint_ip
    link.endpoint_port = (
        report.get("endpoint_port") or link.endpoint_port or node.endpoint_port
    )
    link.reflected_endpoint_ip = reflected_endpoint_ip or link.reflected_endpoint_ip
    link.wireguard_public_key = (
        report.get("wireguard_public_key") or link.wireguard_public_key
    )
    link.rtt_ms = report.get("rtt_ms")
    link.jitter_ms = report.get("jitter_ms")
    link.loss_pct = report.get("loss_pct")
    link.status = _transport_status_from_metrics(
        rtt_ms=link.rtt_ms,
        jitter_ms=link.jitter_ms,
        loss_pct=link.loss_pct,
    )
    link.last_reported_at = reported_at
    return link


def select_active_transport_links(links: list[TransportLink]) -> list[TransportLink]:
    by_kind: dict[TransportKind, list[TransportLink]] = {}
    for link in links:
        if not link.admin_state_up or link.overlay_vpn_ip is None:
            link.is_active = False
            continue
        by_kind.setdefault(link.kind, []).append(link)

    ordered = sorted(
        [
            max(
                group,
                key=lambda item: (
                    item.status != TransportStatus.DOWN,
                    -item.priority,
                    item.created_at.timestamp() if item.created_at else 0,
                ),
            )
            for group in by_kind.values()
        ],
        key=lambda item: (
            item.status == TransportStatus.DOWN,
            item.priority,
            item.created_at or datetime.now(timezone.utc),
        ),
    )
    for link in links:
        link.is_active = False
    if ordered:
        ordered[0].is_active = True
    return ordered


def canonical_transport_link(links: list[TransportLink]) -> TransportLink | None:
    links = [link for link in links if link.overlay_vpn_ip]
    if not links:
        return None
    internet_links = sorted(
        [link for link in links if link.kind == TransportKind.INTERNET],
        key=lambda item: (item.priority, item.created_at or datetime.now(timezone.utc)),
    )
    if internet_links:
        return internet_links[0]
    links.sort(
        key=lambda item: (item.priority, item.created_at or datetime.now(timezone.utc))
    )
    return links[0]


async def sync_node_compat_fields(session: AsyncSession, node: Node) -> Node:
    transport_link_result = await session.execute(
        select(TransportLink)
        .where(TransportLink.node_id == node.id)
        .order_by(
            TransportLink.is_active.desc(),
            TransportLink.priority.asc(),
            TransportLink.created_at.asc(),
        )
    )
    transport_links = list(transport_link_result.scalars().all())
    active_link = transport_links[0] if transport_links else None
    canonical_link = canonical_transport_link(transport_links)
    primary_prefix = None
    if node.site_id:
        prefix_result = await session.execute(
            select(SitePrefix)
            .where(SitePrefix.site_id == node.site_id, SitePrefix.advertise.is_(True))
            .order_by(SitePrefix.priority.asc(), SitePrefix.created_at.asc())
        )
        primary_prefix = prefix_result.scalars().first()
    node.site_subnet = primary_prefix.prefix if primary_prefix is not None else None
    if canonical_link is not None:
        node.vpn_ip = canonical_link.overlay_vpn_ip or node.vpn_ip
    if active_link is not None:
        node.endpoint_ip = active_link.endpoint_ip or node.endpoint_ip
        node.endpoint_port = active_link.endpoint_port or node.endpoint_port
        node.reflected_endpoint_ip = active_link.reflected_endpoint_ip
        node.reflected_endpoint_port = active_link.reflected_endpoint_port
    return node


async def get_node_by_id(session: AsyncSession, node_id: str) -> Node | None:
    result = await session.execute(
        select(Node)
        .options(
            selectinload(Node.site).selectinload(Site.prefixes),
            selectinload(Node.transport_links),
        )
        .where(Node.id == node_id)
    )
    return result.scalar_one_or_none()


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
            (
                candidate
                for candidate in candidates
                if verify_token(claim_token, candidate.token_hash)
            ),
            None,
        )
        if claim_row is None:
            raise HTTPException(status_code=401, detail="Invalid claim token")
        if claim_row.status in {DeviceClaimStatus.CLAIMED, DeviceClaimStatus.ACTIVE}:
            raise HTTPException(
                status_code=401, detail="Claim token has already been used"
            )
        if claim_row.status == DeviceClaimStatus.REVOKED:
            raise HTTPException(status_code=401, detail="Claim token has been revoked")
        expires_at = claim_row.expires_at
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at and expires_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="Claim token has expired")
        if claim_row.expected_name and claim_row.expected_name != data.name:
            raise HTTPException(
                status_code=409, detail="Node name does not match the device claim"
            )
        if (
            claim_row.site_subnet
            and data.site_subnet
            and claim_row.site_subnet != data.site_subnet
        ):
            raise HTTPException(
                status_code=409, detail="Site subnet does not match the device claim"
            )
    elif settings.REQUIRE_PREAUTH:
        raise HTTPException(
            status_code=401, detail="A claim token is required to register"
        )

    reflected_ip = request.client.host if request.client else None
    claim_id = claim_row.id if claim_row else None
    claim_site_subnet = (
        claim_row.site_subnet if claim_row and claim_row.site_subnet else None
    )
    initial_status = NodeStatus.ACTIVE if claim_row else NodeStatus.PENDING
    site_name = _normalize_site_name(
        claim_row.site_name if claim_row else None,
        data.name,
    )

    for attempt in range(1, MAX_VPN_IP_ALLOCATION_RETRIES + 1):
        vpn_ip = await _allocate_vpn_ip(session)
        now = datetime.now(timezone.utc)
        auth_token, auth_token_prefix, auth_token_hash = issue_hashed_token()
        site = await _get_or_create_site(session, site_name=site_name)
        node = Node(
            name=data.name,
            wireguard_public_key=data.wireguard_public_key,
            endpoint_ip=data.endpoint_ip or reflected_ip,
            endpoint_port=data.endpoint_port,
            vpn_ip=vpn_ip,
            site_subnet=claim_site_subnet or data.site_subnet,
            reflected_endpoint_ip=reflected_ip,
            auth_token_hash=auth_token_hash,
            auth_token_prefix=auth_token_prefix,
            auth_token_issued_at=now,
            device_claim_id=claim_id,
            site_id=site.id,
            status=initial_status,
            last_seen=now,
            created_at=now,
        )
        session.add(node)
        try:
            await session.flush()
        except IntegrityError as exc:
            await session.rollback()
            if (
                _is_vpn_ip_unique_violation(exc)
                and attempt < MAX_VPN_IP_ALLOCATION_RETRIES
            ):
                continue
            raise

        await _upsert_primary_site_prefix(
            session,
            site=site,
            prefix=claim_site_subnet or data.site_subnet,
        )
        await _create_default_transport_link(
            session,
            node=node,
            endpoint_ip=node.endpoint_ip,
            endpoint_port=node.endpoint_port,
            reflected_endpoint_ip=reflected_ip,
            wireguard_public_key=node.wireguard_public_key,
            overlay_vpn_ip=node.vpn_ip,
        )
        await sync_node_compat_fields(session, node)

        if claim_id:
            claim_row = await session.get(DeviceClaim, claim_id)
            if claim_row is None:
                raise HTTPException(
                    status_code=409, detail="Device claim no longer exists"
                )
            claim_row.claimed_at = now
            claim_row.claimed_by_node_id = node.id
            claim_row.status = (
                DeviceClaimStatus.ACTIVE
                if initial_status == NodeStatus.ACTIVE
                else DeviceClaimStatus.CLAIMED
            )

        await event_service.record_event(
            session,
            kind=EventKind.NODE_REGISTERED,
            severity=EventSeverity.INFO,
            title="Node registered",
            message=f"{node.name} registered and {'activated' if initial_status == NodeStatus.ACTIVE else 'awaits activation'}",
            node=node,
        )

        await session.commit()
        return await get_node_by_id(session, node.id), auth_token

    raise HTTPException(status_code=503, detail="Could not allocate a unique VPN IP")


async def update_heartbeat(
    node: Node,
    request: Request,
    session: AsyncSession,
    *,
    transport_links: list[dict] | None = None,
) -> Node:
    now = datetime.now(timezone.utc)
    prior_transport_state = {
        link.kind: {
            "status": link.status,
            "is_active": link.is_active,
        }
        for link in getattr(node, "transport_links", [])
    }
    node.last_seen = now
    if request.client:
        node.reflected_endpoint_ip = request.client.host
    if transport_links:
        for report in transport_links:
            await _upsert_transport_link_report(
                session,
                node=node,
                report=report,
                reflected_endpoint_ip=request.client.host if request.client else None,
                reported_at=now,
            )
        result = await session.execute(
            select(TransportLink).where(TransportLink.node_id == node.id)
        )
        links = list(result.scalars().all())
        selected = select_active_transport_links(links)
        for link in links:
            previous = prior_transport_state.get(link.kind)
            if previous and previous["status"] != link.status:
                await event_service.record_event(
                    session,
                    kind=EventKind.TRANSPORT_STATUS_CHANGED,
                    severity=EventSeverity.WARN
                    if link.status in {TransportStatus.DOWN, TransportStatus.DEGRADED}
                    else EventSeverity.INFO,
                    title="Transport state changed",
                    message=f"{node.name} {link.kind.value} changed from {previous['status'].value.lower()} to {link.status.value.lower()}",
                    node=node,
                    transport_link=link,
                )
            elif previous is None:
                await event_service.record_event(
                    session,
                    kind=EventKind.TRANSPORT_STATUS_CHANGED,
                    severity=EventSeverity.INFO,
                    title="Transport discovered",
                    message=f"{node.name} reported {link.kind.value} transport {link.name}",
                    node=node,
                    transport_link=link,
                )
        previous_active = next(
            (
                kind
                for kind, state in prior_transport_state.items()
                if state["is_active"]
            ),
            None,
        )
        next_active = selected[0].kind if selected else None
        if previous_active != next_active and next_active is not None:
            await event_service.record_event(
                session,
                kind=EventKind.TRANSPORT_FAILOVER,
                severity=EventSeverity.WARN
                if previous_active is not None
                else EventSeverity.INFO,
                title="Active transport changed",
                message=f"{node.name} active path moved from {previous_active.value if previous_active is not None else 'none'} to {next_active.value}",
                node=node,
                transport_link=selected[0],
            )
        if previous_active != next_active:
            policies = await policy_service.list_policies(session)
            for policy in policies:
                if not policy.enabled or not policy_applies_to_node(policy, node):
                    continue
                resolved = resolve_policy_for_node(node, policy)
                if (
                    resolved["resolution"] == "fallback"
                    and resolved["selected"] is not None
                ):
                    await event_service.record_event(
                        session,
                        kind=EventKind.POLICY_FALLBACK_ACTIVE,
                        severity=EventSeverity.WARN,
                        title="Policy running on fallback",
                        message=f"{policy.name} is using fallback transport {resolved['selected'].kind.value} on {node.name}",
                        node=node,
                        transport_link=resolved["selected"],
                    )
    # Auto-recover: an OFFLINE node that heartbeats is back online
    if node.status == NodeStatus.OFFLINE:
        node.status = NodeStatus.ACTIVE
        await event_service.record_event(
            session,
            kind=EventKind.NODE_ACTIVATED,
            severity=EventSeverity.INFO,
            title="Node recovered",
            message=f"{node.name} resumed heartbeats and is active again",
            node=node,
        )
    await sync_node_compat_fields(session, node)
    await session.commit()
    return await get_node_by_id(session, node.id)


def _transport_status_from_metrics(
    *,
    rtt_ms: int | None,
    jitter_ms: int | None,
    loss_pct: int | None,
) -> TransportStatus:
    if loss_pct is not None and loss_pct >= 30:
        return TransportStatus.DOWN
    if loss_pct is not None and loss_pct >= 5:
        return TransportStatus.DEGRADED
    if jitter_ms is not None and jitter_ms >= 100:
        return TransportStatus.DEGRADED
    if rtt_ms is not None and rtt_ms >= 250:
        return TransportStatus.DEGRADED
    if rtt_ms is not None or jitter_ms is not None or loss_pct is not None:
        return TransportStatus.HEALTHY
    return TransportStatus.UNKNOWN


async def expire_stale_nodes(
    session: AsyncSession, threshold_seconds: int
) -> list[Node]:
    """Set ACTIVE nodes to OFFLINE when last_seen is older than threshold_seconds.

    Returns the list of nodes transitioned so callers can clean up data-plane state.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=threshold_seconds)
    result = await session.execute(
        select(Node)
        .options(selectinload(Node.transport_links))
        .where(
            Node.status == NodeStatus.ACTIVE,
            Node.last_seen < cutoff,
        )
    )
    stale = list(result.scalars().all())
    for node in stale:
        node.status = NodeStatus.OFFLINE
        await event_service.record_event(
            session,
            kind=EventKind.NODE_OFFLINE,
            severity=EventSeverity.WARN,
            title="Node offline",
            message=f"{node.name} stopped sending heartbeats",
            node=node,
        )
    if stale:
        await session.commit()
    return stale


async def mark_node_offline(node: Node, session: AsyncSession) -> Node:
    """Immediately mark a node OFFLINE (called on clean agent shutdown)."""
    node.status = NodeStatus.OFFLINE
    await event_service.record_event(
        session,
        kind=EventKind.NODE_OFFLINE,
        severity=EventSeverity.INFO,
        title="Node shutdown",
        message=f"{node.name} reported a clean shutdown",
        node=node,
    )
    await session.commit()
    await session.refresh(node)
    return node


async def activate_node(node_id: str, session: AsyncSession) -> Node:
    node = await get_node_by_id(session, node_id)
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
    await event_service.record_event(
        session,
        kind=EventKind.NODE_ACTIVATED,
        severity=EventSeverity.INFO,
        title="Node activated",
        message=f"{node.name} was activated for service",
        node=node,
    )
    await session.commit()
    return await get_node_by_id(session, node_id)


async def revoke_node(node_id: str, session: AsyncSession) -> Node:
    node = await get_node_by_id(session, node_id)
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
    await event_service.record_event(
        session,
        kind=EventKind.NODE_REVOKED,
        severity=EventSeverity.CRITICAL,
        title="Node revoked",
        message=f"{node.name} was revoked and removed from the mesh",
        node=node,
    )
    await session.commit()
    return await get_node_by_id(session, node_id)


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


async def update_node(
    node_id: str, data: NodeUpdateRequest, session: AsyncSession
) -> Node:
    node = await get_node_by_id(session, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    if data.site_name:
        site = await _get_or_create_site(session, site_name=data.site_name)
        node.site_id = site.id
        node.site = site
    elif node.site is None:
        site = await _get_or_create_site(session, site_name=node.name)
        node.site_id = site.id
        node.site = site
    if node.site is None and node.site_id:
        node.site = await session.get(Site, node.site_id)
    if node.site is not None:
        await _upsert_primary_site_prefix(
            session, site=node.site, prefix=data.site_subnet
        )
    await sync_node_compat_fields(session, node)
    await session.commit()
    return await get_node_by_id(session, node_id)


async def list_all_nodes(session: AsyncSession) -> list[Node]:
    result = await session.execute(
        select(Node)
        .options(
            selectinload(Node.site).selectinload(Site.prefixes),
            selectinload(Node.transport_links),
        )
        .order_by(Node.created_at.asc())
    )
    return list(result.scalars().all())


async def rotate_node_token(node: Node, session: AsyncSession) -> str:
    plaintext, prefix, token_hash = issue_hashed_token()
    node.auth_token_prefix = prefix
    node.auth_token_hash = token_hash
    node.auth_token_issued_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(node)
    return plaintext
