from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import NodeStatus, TransportKind, TransportStatus


class TransportLinkHeartbeatReport(BaseModel):
    name: str = "wan1"
    kind: TransportKind = TransportKind.INTERNET
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
    endpoint_ip: Optional[str] = None
    endpoint_port: Optional[int] = None
    reflected_endpoint_ip: Optional[str] = None
    reflected_endpoint_port: Optional[int] = None
    interface_name: Optional[str] = None
    status: TransportStatus
    rtt_ms: Optional[int] = None
    jitter_ms: Optional[int] = None
    loss_pct: Optional[int] = None
    last_reported_at: Optional[datetime] = None
    is_active: bool
    priority: int


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
    preferred_endpoint: str
    endpoint_port: int
    nat_detected: bool
    site_subnet: Optional[str] = None   # LAN subnet to add to WireGuard AllowedIPs
    site_id: Optional[str] = None
    site_name: Optional[str] = None
    transport_link_id: Optional[str] = None
    transport_kind: Optional[TransportKind] = None


class NodeUpdateRequest(BaseModel):
    site_subnet: Optional[str] = None   # pass null/None to clear
    site_name: Optional[str] = None


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
    active_transport: Optional[TransportLinkResponse] = None
    transport_links: list[TransportLinkResponse] = Field(default_factory=list)


def build_node_admin_response(node) -> NodeAdminResponse:
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
            endpoint_ip=link.endpoint_ip,
            endpoint_port=link.endpoint_port,
            reflected_endpoint_ip=link.reflected_endpoint_ip,
            reflected_endpoint_port=link.reflected_endpoint_port,
            interface_name=link.interface_name,
            status=link.status,
            rtt_ms=link.rtt_ms,
            jitter_ms=link.jitter_ms,
            loss_pct=link.loss_pct,
            last_reported_at=link.last_reported_at,
            is_active=link.is_active,
            priority=link.priority,
        )
        for link in getattr(node, "transport_links", [])
    ]
    active_transport = next((link for link in transport_links if link.is_active), None)

    return NodeAdminResponse(
        id=node.id,
        name=node.name,
        wireguard_public_key=node.wireguard_public_key,
        endpoint_ip=node.endpoint_ip,
        endpoint_port=node.endpoint_port,
        reflected_endpoint_ip=node.reflected_endpoint_ip,
        reflected_endpoint_port=node.reflected_endpoint_port,
        vpn_ip=node.vpn_ip,
        site_subnet=node.site_subnet,
        device_claim_id=node.device_claim_id,
        status=node.status,
        last_seen=node.last_seen,
        created_at=node.created_at,
        site=site,
        active_transport=active_transport,
        transport_links=transport_links,
    )
