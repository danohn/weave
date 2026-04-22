from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_token, hash_token
from app.db.models import DeviceClaim, DeviceClaimStatus
from app.schemas.auth import DeviceClaimCreateRequest


async def create_claim(
    data: DeviceClaimCreateRequest, session: AsyncSession
) -> tuple[DeviceClaim, str]:
    """Create a bootstrap claim and return its plaintext token once."""
    existing = await session.execute(
        select(DeviceClaim).where(DeviceClaim.device_id == data.device_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Device claim already exists")

    plaintext = generate_token()
    claim = DeviceClaim(
        device_id=data.device_id,
        site_name=data.site_name,
        expected_name=data.expected_name,
        site_subnet=data.site_subnet,
        expires_at=data.expires_at,
        status=DeviceClaimStatus.UNCLAIMED,
        token_hash=hash_token(plaintext),
        token_prefix=plaintext[:8],
    )
    session.add(claim)
    await session.commit()
    await session.refresh(claim)
    return claim, plaintext


async def list_claims(session: AsyncSession) -> list[DeviceClaim]:
    result = await session.execute(select(DeviceClaim))
    return list(result.scalars().all())


async def revoke_claim(claim_id: str, session: AsyncSession) -> DeviceClaim:
    result = await session.execute(select(DeviceClaim).where(DeviceClaim.id == claim_id))
    claim = result.scalar_one_or_none()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    if claim.status == DeviceClaimStatus.REVOKED:
        raise HTTPException(status_code=400, detail="Claim is already revoked")
    claim.status = DeviceClaimStatus.REVOKED
    await session.commit()
    await session.refresh(claim)
    return claim


async def delete_claim(claim_id: str, session: AsyncSession) -> None:
    result = await session.execute(select(DeviceClaim).where(DeviceClaim.id == claim_id))
    claim = result.scalar_one_or_none()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    if claim.claimed_at is not None:
        raise HTTPException(status_code=400, detail="Cannot delete a claim that has already been used")
    await session.delete(claim)
    await session.commit()
