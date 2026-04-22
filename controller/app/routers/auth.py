from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin
from app.core.websocket import broadcast_state
from app.db.base import get_session
from app.schemas.auth import (
    DeviceClaimCreateRequest,
    DeviceClaimCreatedResponse,
    DeviceClaimResponse,
)
from app.services import auth_service

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/claims", response_model=DeviceClaimCreatedResponse, status_code=201)
async def create_claim(
    data: DeviceClaimCreateRequest,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_admin),
) -> DeviceClaimCreatedResponse:
    claim, plaintext = await auth_service.create_claim(data, session)
    await broadcast_state(session)
    return DeviceClaimCreatedResponse(
        id=claim.id,
        token=plaintext,
        token_prefix=claim.token_prefix,
        device_id=claim.device_id,
        site_name=claim.site_name,
        expected_name=claim.expected_name,
        site_subnet=claim.site_subnet,
        expires_at=claim.expires_at,
        status=claim.status,
        created_at=claim.created_at,
        claimed_at=claim.claimed_at,
        claimed_by_node_id=claim.claimed_by_node_id,
    )


@router.get("/claims", response_model=list[DeviceClaimResponse])
async def list_claims(
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_admin),
) -> list[DeviceClaimResponse]:
    claims = await auth_service.list_claims(session)
    return [DeviceClaimResponse.model_validate(claim) for claim in claims]


@router.post("/claims/{claim_id}/revoke", response_model=DeviceClaimResponse)
async def revoke_claim(
    claim_id: str,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_admin),
) -> DeviceClaimResponse:
    claim = await auth_service.revoke_claim(claim_id, session)
    await broadcast_state(session)
    return DeviceClaimResponse.model_validate(claim)


@router.delete("/claims/{claim_id}", status_code=204)
async def delete_claim(
    claim_id: str,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_admin),
) -> None:
    await auth_service.delete_claim(claim_id, session)
    await broadcast_state(session)
