from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EventKind, EventSeverity, Node, SiteEvent, TransportLink

_LAST_BGP_STATES: dict[str, str] = {}


async def record_event(
    session: AsyncSession,
    *,
    kind: EventKind,
    title: str,
    message: str,
    severity: EventSeverity = EventSeverity.INFO,
    node: Node | None = None,
    transport_link: TransportLink | None = None,
    node_id: str | None = None,
    site_id: str | None = None,
    transport_link_id: str | None = None,
) -> SiteEvent:
    event = SiteEvent(
        kind=kind,
        severity=severity,
        node_id=node.id if node is not None else node_id,
        site_id=(node.site_id if node is not None else site_id),
        transport_link_id=(transport_link.id if transport_link is not None else transport_link_id),
        transport_kind=transport_link.kind if transport_link is not None else None,
        title=title,
        message=message,
        occurred_at=datetime.now(timezone.utc),
    )
    session.add(event)
    await session.flush()
    return event


async def list_recent_events(session: AsyncSession, *, limit: int = 50) -> list[SiteEvent]:
    result = await session.execute(
        select(SiteEvent)
        .order_by(SiteEvent.occurred_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def list_recent_events_by_node(
    session: AsyncSession,
    *,
    node_ids: list[str],
    limit_per_node: int = 8,
) -> dict[str, list[SiteEvent]]:
    if not node_ids:
        return {}
    result = await session.execute(
        select(SiteEvent)
        .where(SiteEvent.node_id.in_(node_ids))
        .order_by(SiteEvent.occurred_at.desc())
        .limit(max(limit_per_node * len(node_ids), limit_per_node))
    )
    grouped: dict[str, list[SiteEvent]] = defaultdict(list)
    for event in result.scalars().all():
        if event.node_id is None:
            continue
        if len(grouped[event.node_id]) < limit_per_node:
            grouped[event.node_id].append(event)
    return grouped


async def record_bgp_state_transitions(
    session: AsyncSession,
    *,
    nodes: list[Node],
    bgp: dict[str, dict],
) -> None:
    overlay_index: dict[str, tuple[Node, TransportLink | None]] = {}
    for node in nodes:
        overlay_index[node.vpn_ip] = (node, None)
        for link in getattr(node, "transport_links", []):
            if link.overlay_vpn_ip:
                overlay_index[link.overlay_vpn_ip] = (node, link)

    changed = False
    current_keys = set(bgp.keys())
    tracked_keys = set(_LAST_BGP_STATES.keys()) | current_keys
    for ip in tracked_keys:
        info = bgp.get(ip)
        current_state = info.get("state") if info else None
        previous_state = _LAST_BGP_STATES.get(ip)
        if current_state == previous_state:
            continue
        _LAST_BGP_STATES[ip] = current_state or ""
        ctx = overlay_index.get(ip)
        if ctx is None:
            continue
        node, link = ctx
        if current_state == "Established" and previous_state not in (None, "", "Established"):
            await record_event(
                session,
                kind=EventKind.BGP_SESSION_ESTABLISHED,
                severity=EventSeverity.INFO,
                title="BGP session established",
                message=f"{node.name} {link.kind.value if link is not None else 'identity'} routing session established",
                node=node,
                transport_link=link,
            )
            changed = True
        elif previous_state == "Established" and current_state != "Established":
            await record_event(
                session,
                kind=EventKind.BGP_SESSION_LOST,
                severity=EventSeverity.WARN,
                title="BGP session lost",
                message=f"{node.name} {link.kind.value if link is not None else 'identity'} routing session moved to {current_state or 'unknown'}",
                node=node,
                transport_link=link,
            )
            changed = True
    if changed:
        await session.commit()
