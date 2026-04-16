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
    STALE_THRESHOLD_SECONDS: int = 120  # mark OFFLINE after this many seconds
    STALE_CHECK_INTERVAL: int = 30      # run the expiry sweep this often
    REQUIRE_PREAUTH: bool = True        # reject registration without a valid pre-auth token


settings = Settings()
