from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class PreAuthTokenCreateRequest(BaseModel):
    label: str


class PreAuthTokenResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    token: str
    label: str
    created_at: datetime
    used_at: Optional[datetime] = None
    used_by_node_id: Optional[str] = None
