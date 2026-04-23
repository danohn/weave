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
from app.db.models import Node, TransportLink

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


async def add_transport_peer(
    link: TransportLink,
    *,
    node_name: str,
    site_subnet: str | None = None,
) -> None:
    """Add or update a node transport link as a WireGuard peer on the controller."""
    endpoint = link.reflected_endpoint_ip or link.endpoint_ip
    if not endpoint or not link.endpoint_port or not link.wireguard_public_key or not link.overlay_vpn_ip:
        logger.warning(
            "WG: skipping peer %s/%s due to incomplete transport config",
            node_name,
            link.kind.value,
        )
        return
    allowed_ips = f"{link.overlay_vpn_ip}/32"
    if link.is_active and site_subnet:
        allowed_ips += f",{site_subnet}"
    try:
        await _wg(
            "set",
            settings.WG_INTERFACE,
            "peer",
            link.wireguard_public_key,
            "allowed-ips",
            allowed_ips,
            "endpoint",
            f"{endpoint}:{link.endpoint_port}",
            "persistent-keepalive",
            "25",
        )
        logger.info("WG: added peer %s/%s (%s)", node_name, link.kind.value, link.overlay_vpn_ip)
    except Exception as exc:
        logger.warning("WG: could not add peer %s/%s: %s", node_name, link.kind.value, exc)


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


async def remove_transport_peer(link: TransportLink, *, node_name: str) -> None:
    """Remove a node transport peer from the controller's wg0."""
    if not link.wireguard_public_key:
        return
    try:
        await _wg(
            "set",
            settings.WG_INTERFACE,
            "peer",
            link.wireguard_public_key,
            "remove",
        )
        logger.info("WG: removed peer %s/%s (%s)", node_name, link.kind.value, link.overlay_vpn_ip)
    except Exception as exc:
        logger.warning("WG: could not remove peer %s/%s: %s", node_name, link.kind.value, exc)


async def sync_peers(nodes: list[Node]) -> None:
    """Add all given nodes as WireGuard peers (used at startup to restore state)."""
    for node in nodes:
        links = sorted(
            [link for link in getattr(node, "transport_links", []) if link.wireguard_public_key and link.overlay_vpn_ip],
            key=lambda item: (item.priority, item.kind.value),
        )
        if links:
            for link in links:
                await add_transport_peer(link, node_name=node.name, site_subnet=node.site_subnet)
        else:
            await add_peer(node)
