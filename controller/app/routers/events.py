from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin
from app.db.base import get_session
from app.schemas.node import SiteEventResponse
from app.services import event_service

router = APIRouter(prefix="/api/v1/events", tags=["events"])


@router.get("/", response_model=list[SiteEventResponse])
async def list_events(
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_admin),
) -> list[SiteEventResponse]:
    return [
        SiteEventResponse.model_validate(event)
        for event in await event_service.list_recent_events(session, limit=limit)
    ]
