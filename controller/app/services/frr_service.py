"""
FRR route reflector management via vtysh.

Neighbors are added/removed with targeted vtysh commands rather than
rewriting frr.conf and reloading, which means changes take effect
immediately without interrupting existing BGP sessions.
"""

import asyncio
import json
import logging

from app.core.config import settings
from app.db.models import Node

logger = logging.getLogger(__name__)

BGP_ASN = 65000


async def _vtysh(*commands: str) -> str:
    """Run vtysh commands asynchronously. Returns stdout. Raises on failure."""
    args = ["vtysh"]
    for cmd in commands:
        args += ["-c", cmd]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode().strip())
    return stdout.decode()


async def get_bgp_status() -> dict[str, dict]:
    """Return BGP neighbor status keyed by VPN IP.

    Queries `show bgp summary json` and returns a dict like:
      {
        "10.0.0.1": {"state": "Established", "uptime": "00:10:15", "prefixes_received": 1},
        "10.0.0.2": {"state": "Active",       "uptime": "never",    "prefixes_received": 0},
      }
    Returns an empty dict if FRR is unreachable.
    """
    try:
        output = await _vtysh("show bgp summary json")
        data = json.loads(output)
        peers = data.get("ipv4Unicast", {}).get("peers", {})
        return {
            ip: {
                "state": peer.get("state", "Unknown"),
                "uptime": peer.get("peerUptime", "never"),
                "prefixes_received": peer.get("pfxRcd", 0),
            }
            for ip, peer in peers.items()
        }
    except Exception as exc:
        logger.warning("BGP: could not get status: %s", exc)
        return {}


async def add_bfd_peer(node: Node) -> None:
    """Pre-register a BFD peer on the route reflector.

    By explicitly creating the BFD session before BGP connects, bfdd can
    complete the handshake independently. When bgpd then checks BFD status
    (on its first connect retry) it will see Up rather than Down, avoiding
    the Idle deadlock.
    """
    try:
        await _vtysh(
            "configure terminal",
            "bfd",
            f"peer {node.vpn_ip} multihop local-address {settings.CONTROLLER_VPN_IP}",
            "end",
            "write memory",
        )
        logger.info("BFD: registered peer %s (%s)", node.name, node.vpn_ip)
    except Exception as exc:
        logger.warning("BFD: could not register peer %s: %s", node.name, exc)


async def remove_bfd_peer(node: Node) -> None:
    """Remove a node's BFD peer entry from the route reflector."""
    try:
        await _vtysh(
            "configure terminal",
            "bfd",
            f"no peer {node.vpn_ip} multihop local-address {settings.CONTROLLER_VPN_IP}",
            "end",
            "write memory",
        )
        logger.info("BFD: removed peer %s (%s)", node.name, node.vpn_ip)
    except Exception as exc:
        logger.warning("BFD: could not remove peer %s: %s", node.name, exc)


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
        # Pre-register the BFD session explicitly so bfdd can establish the
        # handshake with the controller before bgpd tries to connect.
        # This avoids the Idle deadlock caused by bgpd waiting for BFD=Up
        # when BFD hasn't yet been negotiated.
        "bfd",
        f" peer {settings.CONTROLLER_VPN_IP} multihop local-address {node.vpn_ip}",
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
