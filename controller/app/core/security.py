import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.core.config import settings
from app.db.base import get_session
from app.db.models import Node

bearer_scheme = HTTPBearer()


def generate_token() -> str:
    return secrets.token_urlsafe(32)


_hasher = PasswordHasher()


def hash_token(token: str) -> str:
    return _hasher.hash(token)


def verify_token(plaintext: str, token_hash: str) -> bool:
    try:
        return _hasher.verify(token_hash, plaintext)
    except (VerifyMismatchError, InvalidHashError):
        return False


def issue_hashed_token() -> tuple[str, str, str]:
    plaintext = generate_token()
    return plaintext, plaintext[:8], hash_token(plaintext)


async def find_node_for_token(session: AsyncSession, token: str) -> Node | None:
    result = await session.execute(
        select(Node).where(Node.auth_token_prefix == token[:8])
    )
    nodes = list(result.scalars().all())
    return next(
        (
            candidate
            for candidate in nodes
            if verify_token(token, candidate.auth_token_hash)
        ),
        None,
    )


async def get_current_node(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> Node:
    token = credentials.credentials
    node = await find_node_for_token(session, token)
    if node is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return node


def require_admin(request: Request) -> None:
    auth_header = request.headers.get("authorization", "")
    bearer_token = auth_header.removeprefix("Bearer ").strip()
    if bearer_token and bearer_token == settings.ADMIN_TOKEN:
        return
    if request.session.get("user"):
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
    )
