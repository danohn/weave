import socket

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="/etc/weave/agent.env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    # Required
    CONTROLLER_URL: str

    # Optional with sensible defaults
    NODE_NAME: str = socket.gethostname()
    ENDPOINT_PORT: int = 51820
    INTERFACE: str = "wg0"

    STATE_FILE: str = "/etc/weave/state.json"
    PRIVATE_KEY_FILE: str = "/etc/weave/privatekey"

    HEARTBEAT_INTERVAL: int = 30
    PEER_POLL_INTERVAL: int = 60

    CLAIM_TOKEN: str | None = None
    PREAUTH_TOKEN: str | None = None
    TRANSPORT_NAME: str = "wan1"
    TRANSPORT_KIND: str = "internet"
