from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class PreAuthTokenCreateRequest(BaseModel):
    label: str


class PreAuthTokenCreatedResponse(BaseModel):
    """Returned once at creation — includes the plaintext token."""
    id: str
    token: str
    token_prefix: str
    label: str
    created_at: datetime
    used_at: Optional[datetime] = None
    used_by_node_id: Optional[str] = None


class PreAuthTokenResponse(BaseModel):
    """Returned by list/get — never exposes the plaintext token."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    token_prefix: str
    label: str
    created_at: datetime
    used_at: Optional[datetime] = None
    used_by_node_id: Optional[str] = None
