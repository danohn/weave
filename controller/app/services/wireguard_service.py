"""
WireGuard peer management for the controller's wg0 interface.

As nodes activate or are revoked, the controller adds/removes them as
WireGuard peers using `wg set` commands against the in-container wg0
interface. This keeps the overlay topology in sync with the node registry.
"""

import asyncio
import logging
from pathlib import Path

from app.core.config import settings
from app.db.models import Node

logger = logging.getLogger(__name__)


def get_public_key() -> str:
    """Read the controller's WireGuard public key (written by entrypoint.sh)."""
    p = Path(settings.WG_PUBLIC_KEY_FILE)
    return p.read_text().strip() if p.exists() else ""


async def _wg(*args: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "wg", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode().strip())


async def add_peer(node: Node) -> None:
    """Add or update a node as a WireGuard peer on the controller's wg0."""
    endpoint = node.reflected_endpoint_ip or node.endpoint_ip
    allowed_ips = f"{node.vpn_ip}/32"
    if node.site_subnet:
        allowed_ips += f",{node.site_subnet}"
    try:
        await _wg(
            "set", settings.WG_INTERFACE,
            "peer", node.wireguard_public_key,
            "allowed-ips", allowed_ips,
            "endpoint", f"{endpoint}:{node.endpoint_port}",
            "persistent-keepalive", "25",
        )
        logger.info("WG: added peer %s (%s)", node.name, node.vpn_ip)
    except Exception as exc:
        logger.warning("WG: could not add peer %s: %s", node.name, exc)


async def remove_peer(node: Node) -> None:
    """Remove a node's WireGuard peer from the controller's wg0."""
    try:
        await _wg(
            "set", settings.WG_INTERFACE,
            "peer", node.wireguard_public_key,
            "remove",
        )
        logger.info("WG: removed peer %s (%s)", node.name, node.vpn_ip)
    except Exception as exc:
        logger.warning("WG: could not remove peer %s: %s", node.name, exc)


async def sync_peers(nodes: list[Node]) -> None:
    """Add all given nodes as WireGuard peers (used at startup to restore state)."""
    for node in nodes:
        await add_peer(node)
