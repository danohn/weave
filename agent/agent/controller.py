from dataclasses import dataclass

import httpx


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


class ControllerClient:
    def __init__(self, base_url: str) -> None:
        self._base = base_url.rstrip("/")

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
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._base}/api/v1/nodes/register",
                json=payload,
                timeout=10,
            )
            resp.raise_for_status()
            return RegisterResponse(**resp.json())

    async def heartbeat(self, node_id: str, token: str) -> HeartbeatResponse:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._base}/api/v1/nodes/{node_id}/heartbeat",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            resp.raise_for_status()
            return HeartbeatResponse(**resp.json())

    async def get_peers(self, node_id: str, token: str) -> list[Peer]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._base}/api/v1/nodes/{node_id}/peers",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            resp.raise_for_status()
            return [Peer(**p) for p in resp.json()]
