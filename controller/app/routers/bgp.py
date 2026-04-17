from fastapi import APIRouter, Depends

from app.core.security import require_admin
from app.services import frr_service

router = APIRouter(prefix="/api/v1/bgp", tags=["bgp"])


@router.get("/status")
async def bgp_status(
    _: None = Depends(require_admin),
) -> dict:
    """Return BGP session state for all neighbors.

    Keyed by VPN IP. Each entry contains:
      - state: Established | Active | Idle | Connect | …
      - uptime: human-readable session uptime or "never"
      - prefixes_received: number of prefixes received from this peer
    """
    return await frr_service.get_bgp_status()
