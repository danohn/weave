import base64
import hashlib
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx
from authlib.jose import JsonWebKey, jwt
from authlib.jose.errors import JoseError
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.core.config import settings

router = APIRouter(prefix="/auth", tags=["auth-web"])

_discovery_cache: dict | None = None
_jwks_cache: dict[str, Any] | None = None


async def _discover() -> dict:
    global _discovery_cache
    if _discovery_cache is None:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{settings.OIDC_ISSUER}/.well-known/openid-configuration",
                timeout=10,
            )
            r.raise_for_status()
            _discovery_cache = r.json()
    return _discovery_cache


async def _fetch_jwks() -> dict[str, Any]:
    global _jwks_cache
    if _jwks_cache is None:
        doc = await _discover()
        async with httpx.AsyncClient() as client:
            r = await client.get(doc["jwks_uri"], timeout=10)
            r.raise_for_status()
            _jwks_cache = r.json()
    return _jwks_cache


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _redirect_uri() -> str:
    if settings.OIDC_REDIRECT_URI:
        return settings.OIDC_REDIRECT_URI
    return f"https://{settings.WEAVE_DOMAIN}/auth/callback"


def _decode_id_token_claims(id_token: str) -> dict:
    jwks = JsonWebKey.import_key_set(_jwks_cache or {"keys": []})
    claims = jwt.decode(
        id_token,
        jwks,
        claims_options={
            "iss": {"essential": True, "value": settings.OIDC_ISSUER},
            "aud": {"essential": True, "value": settings.OIDC_CLIENT_ID},
            "exp": {"essential": True},
            "sub": {"essential": True},
        },
    )
    claims.validate(leeway=60)
    return dict(claims)


async def _exchange_code_for_tokens(code: str, verifier: str) -> dict[str, Any]:
    doc = await _discover()
    async with httpx.AsyncClient() as client:
        r = await client.post(
            doc["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _redirect_uri(),
                "client_id": settings.OIDC_CLIENT_ID,
                "client_secret": settings.OIDC_CLIENT_SECRET,
                "code_verifier": verifier,
            },
            timeout=10,
        )
        r.raise_for_status()
        return r.json()


async def _validate_id_token(id_token: str) -> dict[str, Any]:
    await _fetch_jwks()
    try:
        return _decode_id_token_claims(id_token)
    except JoseError as exc:
        raise ValueError("Invalid ID token") from exc


@router.get("/login")
async def login() -> RedirectResponse:
    return RedirectResponse("/auth/oidc/start")


@router.get("/oidc/start")
async def oidc_start(request: Request) -> RedirectResponse:
    doc = await _discover()
    state = secrets.token_urlsafe(32)
    verifier, challenge = _pkce_pair()

    request.session["oidc_state"] = state
    request.session["oidc_verifier"] = verifier

    params = {
        "response_type": "code",
        "client_id": settings.OIDC_CLIENT_ID,
        "redirect_uri": _redirect_uri(),
        "scope": settings.OIDC_SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    auth_url = doc["authorization_endpoint"] + "?" + urlencode(params)
    return RedirectResponse(auth_url)


@router.get("/callback")
async def oidc_callback(
    request: Request,
    code: str,
    state: str,
) -> RedirectResponse:
    expected_state = request.session.pop("oidc_state", None)
    verifier = request.session.pop("oidc_verifier", None)

    if not expected_state or state != expected_state:
        return JSONResponse({"detail": "Invalid state parameter"}, status_code=400)
    if not verifier:
        return JSONResponse({"detail": "Missing PKCE verifier"}, status_code=400)

    tokens = await _exchange_code_for_tokens(code, verifier)
    try:
        claims = await _validate_id_token(tokens["id_token"])
    except ValueError:
        return JSONResponse({"detail": "Invalid ID token"}, status_code=401)

    if settings.OIDC_ADMIN_GROUP:
        groups = claims.get("groups", [])
        if settings.OIDC_ADMIN_GROUP not in groups:
            return JSONResponse(
                {"detail": "Forbidden: not in required group"}, status_code=403
            )

    username = (
        claims.get("preferred_username")
        or claims.get("name")
        or claims.get("email")
        or claims.get("sub")
    )
    request.session["user"] = {
        "sub": claims.get("sub"),
        "username": username,
        "email": claims.get("email"),
    }

    return RedirectResponse("/")


@router.get("/logout")
@router.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()

    try:
        doc = await _discover()
        end_session = doc.get("end_session_endpoint")
    except Exception:
        end_session = None

    if end_session:
        post_logout_uri = f"https://{settings.WEAVE_DOMAIN}"
        return RedirectResponse(
            end_session + "?" + urlencode({"post_logout_redirect_uri": post_logout_uri})
        )

    return RedirectResponse("/")


@router.get("/me")
async def me(request: Request) -> JSONResponse:
    user = request.session.get("user")
    if not user:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    return JSONResponse({"username": user["username"], "email": user["email"]})
