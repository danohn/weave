import base64
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs, urlparse

from httpx import AsyncClient

from app.core.config import settings
from app.routers import auth_web


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _make_hs256_jwt(claims: dict, *, secret: str, kid: str = "test-key") -> str:
    header = {"alg": "HS256", "typ": "JWT", "kid": kid}
    signing_input = ".".join(
        [
            _b64url(json.dumps(header, separators=(",", ":")).encode()),
            _b64url(json.dumps(claims, separators=(",", ":")).encode()),
        ]
    )
    signature = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(signature)}"


async def _start_oidc(secure_client: AsyncClient, monkeypatch) -> str:
    monkeypatch.setattr(settings, "OIDC_ISSUER", "https://issuer.example")
    monkeypatch.setattr(settings, "OIDC_CLIENT_ID", "weave-ui")
    monkeypatch.setattr(settings, "OIDC_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(settings, "OIDC_ADMIN_GROUP", "weave-admins")
    monkeypatch.setattr(settings, "WEAVE_DOMAIN", "weave.example")
    auth_web._discovery_cache = None
    auth_web._jwks_cache = None

    async def fake_discover() -> dict:
        return {
            "authorization_endpoint": "https://issuer.example/authorize",
            "token_endpoint": "https://issuer.example/token",
            "jwks_uri": "https://issuer.example/jwks.json",
        }

    monkeypatch.setattr(auth_web, "_discover", fake_discover)

    response = await secure_client.get("/auth/oidc/start")
    assert response.status_code in {302, 307}
    params = parse_qs(urlparse(response.headers["location"]).query)
    return params["state"][0]


async def test_oidc_callback_accepts_valid_signed_id_token(
    secure_client: AsyncClient,
    monkeypatch,
):
    state = await _start_oidc(secure_client, monkeypatch)
    jwks = {
        "keys": [
            {
                "kty": "oct",
                "kid": "test-key",
                "alg": "HS256",
                "k": _b64url(b"signing-secret"),
            }
        ]
    }
    claims = {
        "iss": settings.OIDC_ISSUER,
        "aud": settings.OIDC_CLIENT_ID,
        "sub": "user-123",
        "preferred_username": "daniel",
        "email": "daniel@example.com",
        "groups": ["weave-admins"],
        "exp": int(time.time()) + 300,
    }

    async def fake_exchange_code_for_tokens(code: str, verifier: str) -> dict:
        return {"id_token": _make_hs256_jwt(claims, secret="signing-secret")}

    async def fake_fetch_jwks() -> dict:
        auth_web._jwks_cache = jwks
        return jwks

    monkeypatch.setattr(auth_web, "_exchange_code_for_tokens", fake_exchange_code_for_tokens)
    monkeypatch.setattr(auth_web, "_fetch_jwks", fake_fetch_jwks)

    callback = await secure_client.get(f"/auth/callback?code=test-code&state={state}")
    assert callback.status_code in {302, 307}
    assert callback.headers["location"] == "/"

    me = await secure_client.get("/auth/me")
    assert me.status_code == 200
    assert me.json() == {
        "username": "daniel",
        "email": "daniel@example.com",
    }


async def test_oidc_callback_rejects_invalid_id_token_signature(
    secure_client: AsyncClient,
    monkeypatch,
):
    state = await _start_oidc(secure_client, monkeypatch)
    jwks = {
        "keys": [
            {
                "kty": "oct",
                "kid": "test-key",
                "alg": "HS256",
                "k": _b64url(b"trusted-secret"),
            }
        ]
    }
    claims = {
        "iss": settings.OIDC_ISSUER,
        "aud": settings.OIDC_CLIENT_ID,
        "sub": "user-123",
        "groups": ["weave-admins"],
        "exp": int(time.time()) + 300,
    }

    async def fake_exchange_code_for_tokens(code: str, verifier: str) -> dict:
        return {"id_token": _make_hs256_jwt(claims, secret="forged-secret")}

    async def fake_fetch_jwks() -> dict:
        auth_web._jwks_cache = jwks
        return jwks

    monkeypatch.setattr(auth_web, "_exchange_code_for_tokens", fake_exchange_code_for_tokens)
    monkeypatch.setattr(auth_web, "_fetch_jwks", fake_fetch_jwks)

    callback = await secure_client.get(f"/auth/callback?code=test-code&state={state}")
    assert callback.status_code == 401
    assert callback.json()["detail"] == "Invalid ID token"

    me = await secure_client.get("/auth/me")
    assert me.status_code == 401

