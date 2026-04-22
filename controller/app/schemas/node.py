from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.db.models import NodeStatus


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


class NodeUpdateRequest(BaseModel):
    site_subnet: Optional[str] = None   # pass null/None to clear


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
