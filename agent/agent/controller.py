from dataclasses import dataclass

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
class Peer:
    name: str
    wireguard_public_key: str
    vpn_ip: str
    preferred_endpoint: str
    endpoint_port: int
    site_subnet: str | None = None


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
        preauth_token: str | None = None,
    ) -> RegisterResponse:
        payload: dict = {
            "name": name,
            "wireguard_public_key": wireguard_public_key,
            "endpoint_port": endpoint_port,
        }
        if preauth_token is not None:
            payload["preauth_token"] = preauth_token
        resp = await self._client.post(
            f"{self._base}/api/v1/nodes/register",
            json=payload,
        )
        resp.raise_for_status()
        return RegisterResponse(**resp.json())

    async def heartbeat(self, node_id: str, token: str) -> HeartbeatResponse:
        resp = await self._client.post(
            f"{self._base}/api/v1/nodes/{node_id}/heartbeat",
            headers={"Authorization": f"Bearer {token}"},
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
        known = {f for f in Peer.__dataclass_fields__}
        return [Peer(**{k: v for k, v in p.items() if k in known}) for p in resp.json()]

    async def get_frr_config(self, node_id: str, token: str) -> str:
        """Fetch the FRR BGP config for this node from the controller."""
        resp = await self._client.get(
            f"{self._base}/api/v1/nodes/{node_id}/frr-config",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        return resp.text
