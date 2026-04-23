from dataclasses import asdict, dataclass

import httpx
import websockets


@dataclass
class RegisterResponse:
    id: str
    auth_token: str
    vpn_ip: str


@dataclass
class HeartbeatResponse:
    status: str
    last_seen: str


@dataclass
class TransportLinkHeartbeat:
    name: str = "wan1"
    kind: str = "internet"
    wireguard_public_key: str | None = None
    endpoint_ip: str | None = None
    endpoint_port: int | None = None
    interface_name: str | None = None
    rtt_ms: int | None = None
    jitter_ms: int | None = None
    loss_pct: int | None = None


@dataclass
class Peer:
    name: str
    wireguard_public_key: str
    vpn_ip: str
    preferred_endpoint: str
    endpoint_port: int
    overlay_vpn_ip: str | None = None
    site_subnet: str | None = None
    site_id: str | None = None
    site_name: str | None = None
    transport_link_id: str | None = None
    transport_kind: str | None = None


@dataclass
class OverlayTransport:
    interface_name: str
    name: str
    kind: str
    wireguard_public_key: str
    overlay_vpn_ip: str
    controller_vpn_ip: str
    endpoint_port: int
    priority: int
    is_active: bool


@dataclass
class OverlayConfig:
    transports: list[OverlayTransport]
    peers: list[Peer]
    destination_policies: list["DestinationPolicy"]


@dataclass
class DestinationPolicy:
    id: str
    name: str
    destination_prefix: str
    description: str | None = None
    preferred_transport: str | None = None
    fallback_transport: str | None = None
    selected_transport: str | None = None
    selected_interface: str | None = None
    priority: int = 100
    enabled: bool = True


def parse_peer(data: dict) -> Peer:
    known = {field for field in Peer.__dataclass_fields__}
    return Peer(**{k: v for k, v in data.items() if k in known})


def parse_register_response(data: dict) -> RegisterResponse:
    known = {field for field in RegisterResponse.__dataclass_fields__}
    return RegisterResponse(**{k: v for k, v in data.items() if k in known})


def parse_overlay_transport(data: dict) -> OverlayTransport:
    known = {field for field in OverlayTransport.__dataclass_fields__}
    return OverlayTransport(**{k: v for k, v in data.items() if k in known})


def parse_overlay_config(data: dict) -> OverlayConfig:
    return OverlayConfig(
        transports=[parse_overlay_transport(item) for item in data.get("transports", [])],
        peers=[parse_peer(item) for item in data.get("peers", [])],
        destination_policies=[
            DestinationPolicy(**item) for item in data.get("destination_policies", [])
        ],
    )


class ControllerClient:
    def __init__(self, base_url: str) -> None:
        self._base = base_url.rstrip("/")
        # Persistent client — shares connection pool and TLS sessions across calls
        self._client = httpx.AsyncClient(timeout=10)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def register(
        self,
        name: str,
        wireguard_public_key: str,
        endpoint_port: int,
        claim_token: str | None = None,
    ) -> RegisterResponse:
        payload: dict = {
            "name": name,
            "wireguard_public_key": wireguard_public_key,
            "endpoint_port": endpoint_port,
        }
        if claim_token is not None:
            payload["claim_token"] = claim_token
        resp = await self._client.post(
            f"{self._base}/api/v1/nodes/register",
            json=payload,
        )
        resp.raise_for_status()
        return parse_register_response(resp.json())

    async def heartbeat(
        self,
        node_id: str,
        token: str,
        transport_links: list[TransportLinkHeartbeat] | None = None,
    ) -> HeartbeatResponse:
        payload = {
            "transport_links": [asdict(item) for item in (transport_links or [])]
        }
        resp = await self._client.post(
            f"{self._base}/api/v1/nodes/{node_id}/heartbeat",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        resp.raise_for_status()
        return HeartbeatResponse(**resp.json())

    async def go_offline(self, node_id: str, token: str) -> None:
        """Notify the controller that this node is shutting down cleanly."""
        resp = await self._client.post(
            f"{self._base}/api/v1/nodes/{node_id}/offline",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        resp.raise_for_status()

    async def rotate_token(self, node_id: str, token: str) -> str:
        resp = await self._client.post(
            f"{self._base}/api/v1/nodes/{node_id}/rotate-token",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        return resp.json()["auth_token"]

    def peer_websocket(self, node_id: str, token: str):
        """Return a websockets connection context manager for the peer update stream.

        The auth token is sent as a header rather than a query parameter to
        avoid it appearing in proxy access logs.
        """
        ws_url = (
            self._base
            .replace("https://", "wss://")
            .replace("http://", "ws://")
        )
        ws_url += f"/api/v1/nodes/{node_id}/ws"
        return websockets.connect(
            ws_url,
            additional_headers={"Authorization": f"Bearer {token}"},
        )

    async def get_peers(self, node_id: str, token: str) -> list[Peer]:
        resp = await self._client.get(
            f"{self._base}/api/v1/nodes/{node_id}/peers",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        return [parse_peer(p) for p in resp.json()]

    async def get_frr_config(self, node_id: str, token: str) -> str:
        """Fetch the FRR BGP config for this node from the controller."""
        resp = await self._client.get(
            f"{self._base}/api/v1/nodes/{node_id}/frr-config",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        return resp.text

    async def get_overlay_config(self, node_id: str, token: str) -> OverlayConfig:
        resp = await self._client.get(
            f"{self._base}/api/v1/nodes/{node_id}/overlay-config",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        return parse_overlay_config(resp.json())
