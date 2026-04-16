from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.db.models import NodeStatus


class NodeRegisterRequest(BaseModel):
    name: str
    wireguard_public_key: str
    endpoint_port: int
    # endpoint_ip is derived from request.client.host by the controller
    # vpn_ip is auto-assigned by the controller from VPN_SUBNET
    preauth_token: Optional[str] = None


class NodeRegisterResponse(BaseModel):
    id: str
    auth_token: str
    vpn_ip: str


class HeartbeatResponse(BaseModel):
    status: NodeStatus
    last_seen: datetime


class PeerResponse(BaseModel):
    name: str
    wireguard_public_key: str
    vpn_ip: str
    preferred_endpoint: str
    endpoint_port: int


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
    status: NodeStatus
    last_seen: datetime
    created_at: datetime
