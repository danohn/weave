from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.db.models import DeviceClaimStatus


class DeviceClaimCreateRequest(BaseModel):
    device_id: str
    site_name: Optional[str] = None
    expected_name: Optional[str] = None
    site_subnet: Optional[str] = None
    expires_at: Optional[datetime] = None


class DeviceClaimCreatedResponse(BaseModel):
    """Returned once at creation — includes the plaintext claim token."""
    id: str
    token: str
    token_prefix: str
    device_id: str
    site_name: Optional[str] = None
    expected_name: Optional[str] = None
    site_subnet: Optional[str] = None
    expires_at: Optional[datetime] = None
    status: DeviceClaimStatus
    created_at: datetime
    claimed_at: Optional[datetime] = None
    claimed_by_node_id: Optional[str] = None


class DeviceClaimResponse(BaseModel):
    """Returned by list/get — never exposes the plaintext token."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    token_prefix: str
    device_id: str
    site_name: Optional[str] = None
    expected_name: Optional[str] = None
    site_subnet: Optional[str] = None
    expires_at: Optional[datetime] = None
    status: DeviceClaimStatus
    created_at: datetime
    claimed_at: Optional[datetime] = None
    claimed_by_node_id: Optional[str] = None
