from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_token, hash_token
from app.db.models import PreAuthToken


async def create_token(label: str, session: AsyncSession) -> tuple[PreAuthToken, str]:
    """Create a pre-auth token. Returns (db row, plaintext) — plaintext is never stored."""
    plaintext = generate_token()
    token = PreAuthToken(
        token_hash=hash_token(plaintext),
        token_prefix=plaintext[:8],
        label=label,
    )
    session.add(token)
    await session.commit()
    await session.refresh(token)
    return token, plaintext


async def list_tokens(session: AsyncSession) -> list[PreAuthToken]:
    result = await session.execute(select(PreAuthToken))
    return list(result.scalars().all())


async def delete_token(token_id: str, session: AsyncSession) -> None:
    result = await session.execute(
        select(PreAuthToken).where(PreAuthToken.id == token_id)
    )
    token = result.scalar_one_or_none()
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")
    if token.used_at is not None:
        raise HTTPException(status_code=400, detail="Cannot delete a token that has already been used")
    await session.delete(token)
    await session.commit()
