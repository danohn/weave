import socket
from dataclasses import dataclass
import json

from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass
class TransportConfig:
    name: str
    kind: str
    interface: str
    endpoint_port: int
    private_key_file: str
    bind_interface: str | None = None
    source_ip: str | None = None
    gateway: str | None = None


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
    INTERFACE: str = "weave-internet"

    BIND_INTERFACE: str | None = None
    SOURCE_IP: str | None = None
    GATEWAY: str | None = None
    STATE_FILE: str = "/etc/weave/state.json"
    PRIVATE_KEY_FILE: str = "/etc/weave/privatekey"

    HEARTBEAT_INTERVAL: int = 30
    PEER_POLL_INTERVAL: int = 60

    CLAIM_TOKEN: str | None = None
    PREAUTH_TOKEN: str | None = None
    TRANSPORT_NAME: str = "wan1"
    TRANSPORT_KIND: str = "internet"
    TRANSPORTS_JSON: str | None = None

    def transport_configs(self) -> list[TransportConfig]:
        if not self.TRANSPORTS_JSON:
            return [
                TransportConfig(
                    name=self.TRANSPORT_NAME,
                    kind=self.TRANSPORT_KIND,
                    interface=self.INTERFACE,
                    endpoint_port=self.ENDPOINT_PORT,
                    private_key_file=self.PRIVATE_KEY_FILE,
                    bind_interface=self.BIND_INTERFACE,
                    source_ip=self.SOURCE_IP,
                    gateway=self.GATEWAY,
                )
            ]
        data = json.loads(self.TRANSPORTS_JSON)
        return [
            TransportConfig(
                name=item["name"],
                kind=item["kind"],
                interface=item.get("interface", f"weave-{item['kind']}"),
                endpoint_port=int(item.get("endpoint_port", self.ENDPOINT_PORT)),
                private_key_file=item.get(
                    "private_key_file",
                    f"/etc/weave/privatekey-{item['kind']}",
                ),
                bind_interface=item.get("bind_interface"),
                source_ip=item.get("source_ip"),
                gateway=item.get("gateway"),
            )
            for item in data
        ]
