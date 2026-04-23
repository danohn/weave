from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import EventKind, EventSeverity, NodeStatus, TransportKind, TransportStatus
from app.services.policy_resolver import policy_applies_to_node, resolve_policy_for_node


class TransportLinkHeartbeatReport(BaseModel):
    name: str = "wan1"
    kind: TransportKind = TransportKind.INTERNET
    wireguard_public_key: Optional[str] = None
    endpoint_ip: Optional[str] = None
    endpoint_port: Optional[int] = None
    interface_name: Optional[str] = None
    rtt_ms: Optional[int] = None
    jitter_ms: Optional[int] = None
    loss_pct: Optional[int] = None


class HeartbeatRequest(BaseModel):
    transport_links: list[TransportLinkHeartbeatReport] = Field(default_factory=list)


class SitePrefixResponse(BaseModel):
    id: str
    prefix: str
    advertise: bool
    priority: int


class SiteSummaryResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    primary_prefix: Optional[str] = None
    prefixes: list[SitePrefixResponse] = Field(default_factory=list)


class TransportLinkResponse(BaseModel):
    id: str
    name: str
    kind: TransportKind
    wireguard_public_key: Optional[str] = None
    overlay_vpn_ip: Optional[str] = None
    controller_vpn_ip: Optional[str] = None
    endpoint_ip: Optional[str] = None
    endpoint_port: Optional[int] = None
    reflected_endpoint_ip: Optional[str] = None
    reflected_endpoint_port: Optional[int] = None
    interface_name: Optional[str] = None
    status: TransportStatus
    rtt_ms: Optional[int] = None
    jitter_ms: Optional[int] = None
    loss_pct: Optional[int] = None
    bfd_status: Optional[str] = None
    last_reported_at: Optional[datetime] = None
    is_active: bool
    priority: int


class SiteEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: EventKind
    severity: EventSeverity
    transport_kind: Optional[TransportKind] = None
    title: str
    message: str
    occurred_at: datetime


class SitePolicySummaryResponse(BaseModel):
    total: int = 0
    preferred_active: int = 0
    fallback_active: int = 0
    unresolved: int = 0


class NodeRegisterRequest(BaseModel):
    name: str
    wireguard_public_key: str
    endpoint_ip: Optional[str] = None
    endpoint_port: int
    site_subnet: Optional[str] = None   # e.g. "192.168.1.0/24" — LAN behind this node
    # endpoint_ip is derived from request.client.host by the controller
    # vpn_ip is auto-assigned by the controller from VPN_SUBNET
    claim_token: Optional[str] = None
    preauth_token: Optional[str] = None   # deprecated alias for claim_token


class NodeRegisterResponse(BaseModel):
    id: str
    auth_token: str
    vpn_ip: str
    device_claim_id: Optional[str] = None


class NodeTokenRotateResponse(BaseModel):
    auth_token: str


class HeartbeatResponse(BaseModel):
    status: NodeStatus
    last_seen: datetime


class PeerResponse(BaseModel):
    name: str
    wireguard_public_key: str
    vpn_ip: str
    overlay_vpn_ip: Optional[str] = None
    preferred_endpoint: str
    endpoint_port: int
    nat_detected: bool
    site_subnet: Optional[str] = None   # LAN subnet to add to WireGuard AllowedIPs
    site_id: Optional[str] = None
    site_name: Optional[str] = None
    transport_link_id: Optional[str] = None
    transport_kind: Optional[TransportKind] = None


class OverlayTransportConfig(BaseModel):
    interface_name: str
    name: str
    kind: TransportKind
    wireguard_public_key: str
    overlay_vpn_ip: str
    controller_vpn_ip: str
    endpoint_port: int
    priority: int
    is_active: bool


class DestinationPolicyResponse(BaseModel):
    id: str
    name: str
    destination_prefix: str
    description: Optional[str] = None
    site_id: Optional[str] = None
    site_name: Optional[str] = None
    node_id: Optional[str] = None
    node_name: Optional[str] = None
    preferred_transport: TransportKind
    fallback_transport: Optional[TransportKind] = None
    selected_transport: Optional[TransportKind] = None
    selected_interface: Optional[str] = None
    priority: int
    enabled: bool


class OverlayConfigResponse(BaseModel):
    transports: list[OverlayTransportConfig] = Field(default_factory=list)
    peers: list[PeerResponse] = Field(default_factory=list)
    destination_policies: list[DestinationPolicyResponse] = Field(default_factory=list)


class NodeUpdateRequest(BaseModel):
    site_subnet: Optional[str] = None   # pass null/None to clear
    site_name: Optional[str] = None


class DestinationPolicyCreateRequest(BaseModel):
    name: str
    destination_prefix: str
    description: Optional[str] = None
    site_id: Optional[str] = None
    node_id: Optional[str] = None
    preferred_transport: TransportKind
    fallback_transport: Optional[TransportKind] = None
    priority: int = 100
    enabled: bool = True


class DestinationPolicyUpdateRequest(BaseModel):
    description: Optional[str] = None
    site_id: Optional[str] = None
    node_id: Optional[str] = None
    preferred_transport: Optional[TransportKind] = None
    fallback_transport: Optional[TransportKind] = None
    priority: Optional[int] = None
    enabled: Optional[bool] = None


class NodeAdminResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    wireguard_public_key: str
    endpoint_ip: str
    endpoint_port: int
    reflected_endpoint_ip: Optional[str] = None
    reflected_endpoint_port: Optional[int] = None
    vpn_ip: str
    site_subnet: Optional[str] = None
    device_claim_id: Optional[str] = None
    status: NodeStatus
    last_seen: datetime
    created_at: datetime
    site: Optional[SiteSummaryResponse] = None
    active_overlay_vpn_ip: Optional[str] = None
    active_overlay_interface: Optional[str] = None
    active_transport: Optional[TransportLinkResponse] = None
    transport_links: list[TransportLinkResponse] = Field(default_factory=list)
    health: str = "Healthy"
    exceptions: list[str] = Field(default_factory=list)
    recent_events: list[SiteEventResponse] = Field(default_factory=list)
    policy_summary: SitePolicySummaryResponse = Field(default_factory=SitePolicySummaryResponse)


def _canonical_transport_link(node):
    links = [
        link
        for link in getattr(node, "transport_links", [])
        if getattr(link, "overlay_vpn_ip", None)
    ]
    if not links:
        return None
    internet_links = sorted(
        [link for link in links if link.kind == TransportKind.INTERNET],
        key=lambda item: (
            item.priority,
            item.created_at or datetime.min,
        ),
    )
    if internet_links:
        return internet_links[0]
    links.sort(key=lambda item: (item.priority, item.created_at or datetime.min))
    return links[0]


def _build_policy_summary(node, policies) -> tuple[SitePolicySummaryResponse, list[str]]:
    summary = SitePolicySummaryResponse()
    exceptions: list[str] = []
    applicable = [policy for policy in policies if policy_applies_to_node(policy, node)]
    summary.total = len(applicable)
    for policy in applicable:
        resolved = resolve_policy_for_node(node, policy)
        resolution = resolved["resolution"]
        selected = resolved["selected"]
        if resolution == "preferred":
            summary.preferred_active += 1
        elif resolution == "fallback":
            summary.fallback_active += 1
            exceptions.append(
                f"Policy {policy.name} is running on fallback {selected.kind.value if selected is not None else 'transport'}"
            )
        else:
            summary.unresolved += 1
            exceptions.append(f"Policy {policy.name} has no available transport")
    return summary, exceptions


def _derive_health(node, active_transport, transport_links, bgp, policy_exceptions: list[str]) -> tuple[str, list[str]]:
    exceptions: list[str] = []
    if node.status == NodeStatus.REVOKED:
        return "Down", ["Node is revoked"]
    if node.status != NodeStatus.ACTIVE:
        exceptions.append(f"Node status is {node.status.value.lower()}")
    if not transport_links:
        exceptions.append("No transport links reported")
    down_links = [link for link in transport_links if link.status == TransportStatus.DOWN]
    degraded_links = [link for link in transport_links if link.status == TransportStatus.DEGRADED]
    unmeasured_links = [link for link in transport_links if link.status == TransportStatus.UNKNOWN]
    if down_links:
        exceptions.append(f"{len(down_links)} transport link{'s' if len(down_links) != 1 else ''} down")
    if degraded_links:
        exceptions.append(f"{len(degraded_links)} transport link{'s' if len(degraded_links) != 1 else ''} degraded")
    if active_transport is not None and active_transport.overlay_vpn_ip:
        bgp_info = bgp.get(active_transport.overlay_vpn_ip)
        if bgp_info is None:
            exceptions.append("No routing session reported for active transport")
        elif bgp_info.get("state") != "Established":
            exceptions.append(f"Active transport BGP is {bgp_info.get('state', 'unknown').lower()}")
        bfd_status = bgp_info.get("bfd_status") if bgp_info else None
        if bfd_status and bfd_status not in {"Up", "OK"}:
            exceptions.append(f"Active transport BFD is {bfd_status.lower()}")
    if unmeasured_links and not down_links and not degraded_links:
        exceptions.append(f"{len(unmeasured_links)} transport link{'s' if len(unmeasured_links) != 1 else ''} unmeasured")
    exceptions.extend(policy_exceptions)

    if node.status == NodeStatus.REVOKED:
        health = "Down"
    elif node.status != NodeStatus.ACTIVE:
        health = "Degraded"
    elif active_transport is None:
        health = "Down"
    elif any("no available transport" in item for item in policy_exceptions):
        health = "Degraded"
    elif any(link.status == TransportStatus.DOWN for link in transport_links) or any(link.status == TransportStatus.DEGRADED for link in transport_links):
        health = "Degraded"
    elif active_transport.overlay_vpn_ip and bgp.get(active_transport.overlay_vpn_ip, {}).get("state") not in {None, "Established"}:
        health = "Degraded"
    else:
        health = "Healthy"
    return health, exceptions


def build_node_admin_response(node, *, bgp: Optional[dict] = None, policies: Optional[list] = None, events: Optional[list] = None) -> NodeAdminResponse:
    bgp = bgp or {}
    policies = policies or []
    events = events or []
    site = None
    site_obj = getattr(node, "site", None)
    if site_obj is not None:
        prefixes = [
            SitePrefixResponse(
                id=prefix.id,
                prefix=prefix.prefix,
                advertise=prefix.advertise,
                priority=prefix.priority,
            )
            for prefix in sorted(site_obj.prefixes, key=lambda item: (item.priority, item.created_at))
        ]
        site = SiteSummaryResponse(
            id=site_obj.id,
            name=site_obj.name,
            description=site_obj.description,
            primary_prefix=prefixes[0].prefix if prefixes else None,
            prefixes=prefixes,
        )

    transport_links = [
        TransportLinkResponse(
            id=link.id,
            name=link.name,
            kind=link.kind,
            wireguard_public_key=link.wireguard_public_key,
            overlay_vpn_ip=link.overlay_vpn_ip,
            controller_vpn_ip=link.controller_vpn_ip,
            endpoint_ip=link.endpoint_ip,
            endpoint_port=link.endpoint_port,
            reflected_endpoint_ip=link.reflected_endpoint_ip,
            reflected_endpoint_port=link.reflected_endpoint_port,
            interface_name=link.interface_name,
            status=link.status,
            rtt_ms=link.rtt_ms,
            jitter_ms=link.jitter_ms,
            loss_pct=link.loss_pct,
            bfd_status=bgp.get(link.overlay_vpn_ip or "", {}).get("bfd_status"),
            last_reported_at=link.last_reported_at,
            is_active=link.is_active,
            priority=link.priority,
        )
        for link in getattr(node, "transport_links", [])
    ]
    active_transport = next((link for link in transport_links if link.is_active), None)
    canonical_transport = _canonical_transport_link(node)
    policy_summary, policy_exceptions = _build_policy_summary(node, policies)
    health, exceptions = _derive_health(node, active_transport, transport_links, bgp, policy_exceptions)
    recent_events = [
        SiteEventResponse(
            id=event.id,
            kind=event.kind,
            severity=event.severity,
            transport_kind=event.transport_kind,
            title=event.title,
            message=event.message,
            occurred_at=event.occurred_at,
        )
        for event in events
    ]

    return NodeAdminResponse(
        id=node.id,
        name=node.name,
        wireguard_public_key=node.wireguard_public_key,
        endpoint_ip=node.endpoint_ip,
        endpoint_port=node.endpoint_port,
        reflected_endpoint_ip=node.reflected_endpoint_ip,
        reflected_endpoint_port=node.reflected_endpoint_port,
        vpn_ip=canonical_transport.overlay_vpn_ip if canonical_transport is not None else node.vpn_ip,
        site_subnet=node.site_subnet,
        device_claim_id=node.device_claim_id,
        status=node.status,
        last_seen=node.last_seen,
        created_at=node.created_at,
        site=site,
        active_overlay_vpn_ip=active_transport.overlay_vpn_ip if active_transport is not None else None,
        active_overlay_interface=active_transport.interface_name if active_transport is not None else None,
        active_transport=active_transport,
        transport_links=transport_links,
        health=health,
        exceptions=exceptions,
        recent_events=recent_events,
        policy_summary=policy_summary,
    )
