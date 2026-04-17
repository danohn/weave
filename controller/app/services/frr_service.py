"""
FRR route reflector management via vtysh.

Neighbors are added/removed with targeted vtysh commands rather than
rewriting frr.conf and reloading, which means changes take effect
immediately without interrupting existing BGP sessions.
"""

import asyncio
import logging

from app.core.config import settings
from app.db.models import Node

logger = logging.getLogger(__name__)

BGP_ASN = 65000


async def _vtysh(*commands: str) -> None:
    """Run vtysh commands asynchronously. Logs a warning on failure."""
    args = ["vtysh"]
    for cmd in commands:
        args += ["-c", cmd]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode().strip())


async def add_neighbor(node: Node) -> None:
    """Add a node as a BGP neighbor on the route reflector."""
    try:
        await _vtysh(
            "configure terminal",
            f"router bgp {BGP_ASN}",
            f"neighbor {node.vpn_ip} peer-group NODES",
            "end",
            "write memory",
        )
        logger.info("BGP: added neighbor %s (%s)", node.name, node.vpn_ip)
    except Exception as exc:
        logger.warning("BGP: could not add neighbor %s: %s", node.name, exc)


async def remove_neighbor(node: Node) -> None:
    """Remove a node's BGP neighbor entry from the route reflector."""
    try:
        await _vtysh(
            "configure terminal",
            f"router bgp {BGP_ASN}",
            f"no neighbor {node.vpn_ip}",
            "end",
            "write memory",
        )
        logger.info("BGP: removed neighbor %s (%s)", node.name, node.vpn_ip)
    except Exception as exc:
        logger.warning("BGP: could not remove neighbor %s: %s", node.name, exc)


def generate_node_config(node: Node) -> str:
    """Generate the FRR config for an edge node (fetched via GET /frr-config)."""
    lines = [
        "frr defaults traditional",
        f"hostname {node.name}",
        "log syslog informational",
        "!",
        "bfd",
        "!",
        f"router bgp {BGP_ASN}",
        f" bgp router-id {node.vpn_ip}",
        " no bgp default ipv4-unicast",
        " !",
        f" neighbor {settings.CONTROLLER_VPN_IP} remote-as {BGP_ASN}",
        f" neighbor {settings.CONTROLLER_VPN_IP} update-source wg0",
        f" neighbor {settings.CONTROLLER_VPN_IP} bfd",
        " !",
        " address-family ipv4 unicast",
        f"  neighbor {settings.CONTROLLER_VPN_IP} activate",
        f"  neighbor {settings.CONTROLLER_VPN_IP} soft-reconfiguration inbound",
    ]
    if node.site_subnet:
        lines.append(f"  network {node.site_subnet}")
    lines += [
        " exit-address-family",
        "!",
    ]
    return "\n".join(lines) + "\n"
