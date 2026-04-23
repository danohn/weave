from pydantic_settings import BaseSettings, SettingsConfigDict
import ipaddress


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
    TRANSPORT_OVERLAY_SUBNETS: str = (
        "internet=10.0.0.0/24,mpls=10.0.1.0/24,lte=10.0.2.0/24,other=10.0.3.0/24"
    )

    @property
    def session_cookie_secure(self) -> bool:
        if self.SESSION_COOKIE_SECURE is not None:
            return self.SESSION_COOKIE_SECURE
        return bool(self.WEAVE_DOMAIN)


settings = Settings()


def transport_overlay_subnets() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in settings.TRANSPORT_OVERLAY_SUBNETS.split(","):
        if "=" not in item:
            continue
        kind, subnet = item.split("=", 1)
        mapping[kind.strip()] = subnet.strip()
    return mapping


def controller_overlay_ip_for_kind(kind: str) -> str:
    subnet = transport_overlay_subnets()[kind]
    network = ipaddress.ip_network(subnet, strict=False)
    return str(list(network.hosts())[-1])
