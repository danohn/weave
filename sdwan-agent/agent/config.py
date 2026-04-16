import socket

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="/etc/sdwan-agent/agent.env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    # Required
    CONTROLLER_URL: str
    ENDPOINT_IP: str

    # Optional with sensible defaults
    NODE_NAME: str = socket.gethostname()
    ENDPOINT_PORT: int = 51820
    INTERFACE: str = "wg0"

    STATE_FILE: str = "/etc/sdwan-agent/state.json"
    PRIVATE_KEY_FILE: str = "/etc/sdwan-agent/privatekey"

    HEARTBEAT_INTERVAL: int = 30
    PEER_POLL_INTERVAL: int = 60

    PREAUTH_TOKEN: str | None = None

    @property
    def wg_config_file(self) -> str:
        return f"/etc/wireguard/{self.INTERFACE}.conf"
