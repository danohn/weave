from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin
from app.core.websocket import broadcast_state
from app.db.base import get_session
from app.schemas.auth import PreAuthTokenCreateRequest, PreAuthTokenResponse
from app.services import auth_service

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/tokens", response_model=PreAuthTokenResponse, status_code=201)
async def create_token(
    data: PreAuthTokenCreateRequest,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_admin),
) -> PreAuthTokenResponse:
    token = await auth_service.create_token(data.label, session)
    await broadcast_state(session)
    return PreAuthTokenResponse.model_validate(token)


@router.get("/tokens", response_model=list[PreAuthTokenResponse])
async def list_tokens(
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_admin),
) -> list[PreAuthTokenResponse]:
    tokens = await auth_service.list_tokens(session)
    return [PreAuthTokenResponse.model_validate(t) for t in tokens]


@router.delete("/tokens/{token_id}", status_code=204)
async def delete_token(
    token_id: str,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_admin),
) -> None:
    await auth_service.delete_token(token_id, session)
    await broadcast_state(session)
