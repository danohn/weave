from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    DATABASE_URL: str = "sqlite+aiosqlite:///./weave.db"
    ADMIN_TOKEN: str = "changeme-admin-token"
    VPN_SUBNET: str = "10.0.0.0/24"

    # Session
    SESSION_SECRET: str = "changeme-session-secret"
    SESSION_COOKIE_SECURE: bool | None = None

    # OIDC
    OIDC_ISSUER: str = ""
    OIDC_CLIENT_ID: str = ""
    OIDC_CLIENT_SECRET: str = ""
    OIDC_REDIRECT_URI: str | None = None
    OIDC_SCOPES: str = "openid email profile"
    OIDC_ADMIN_GROUP: str | None = None
    STALE_THRESHOLD_SECONDS: int = 75   # mark OFFLINE after this many seconds (~2.5 heartbeats)
    STALE_CHECK_INTERVAL: int = 15      # run the expiry sweep this often
    REQUIRE_PREAUTH: bool = True        # reject registration without a valid bootstrap claim

    # Controller overlay — WireGuard route reflector running inside the container.
    CONTROLLER_VPN_IP: str = "10.0.0.254"
    CONTROLLER_ENDPOINT_PORT: int = 51820
    WG_INTERFACE: str = "wg0"
    # Public key is read from this file (written by entrypoint.sh at startup)
    WG_PUBLIC_KEY_FILE: str = "/app/data/rr-publickey"
    # Domain agents already use to reach the controller — reused as the
    # WireGuard endpoint hostname so no separate IP config is needed.
    WEAVE_DOMAIN: str = ""

    @property
    def session_cookie_secure(self) -> bool:
        if self.SESSION_COOKIE_SECURE is not None:
            return self.SESSION_COOKIE_SECURE
        return bool(self.WEAVE_DOMAIN)


settings = Settings()
