"""
FRR route reflector management via vtysh.

Neighbors are added/removed with targeted vtysh commands rather than
rewriting frr.conf and reloading, which means changes take effect
immediately without interrupting existing BGP sessions.
"""

import asyncio
import json
import logging

from app.db.models import Node, TransportLink

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


def _route_map_name(link: TransportLink) -> str:
    return f"WEAVE-IN-{link.kind.value.upper()}-{link.node_id[:8]}"


def _local_pref_for_priority(priority: int) -> int:
    return max(50, 500 - priority)


async def add_bfd_peer(link: TransportLink, node_name: str) -> None:
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
            f"peer {link.overlay_vpn_ip} multihop local-address {link.controller_vpn_ip}",
            "end",
            "write memory",
        )
        logger.info("BFD: registered peer %s/%s (%s)", node_name, link.kind.value, link.overlay_vpn_ip)
    except Exception as exc:
        logger.warning("BFD: could not register peer %s/%s: %s", node_name, link.kind.value, exc)


async def remove_bfd_peer(link: TransportLink, node_name: str) -> None:
    """Remove a node's BFD peer entry from the route reflector."""
    try:
        await _vtysh(
            "configure terminal",
            "bfd",
            f"no peer {link.overlay_vpn_ip} multihop local-address {link.controller_vpn_ip}",
            "end",
            "write memory",
        )
        logger.info("BFD: removed peer %s/%s (%s)", node_name, link.kind.value, link.overlay_vpn_ip)
    except Exception as exc:
        logger.warning("BFD: could not remove peer %s/%s: %s", node_name, link.kind.value, exc)


async def add_neighbor(link: TransportLink, node_name: str) -> None:
    """Add a transport link as a BGP neighbor on the route reflector."""
    route_map = _route_map_name(link)
    local_pref = _local_pref_for_priority(link.priority)
    try:
        await _vtysh(
            "configure terminal",
            f"router bgp {BGP_ASN}",
            f"neighbor {link.overlay_vpn_ip} peer-group NODES",
            f"neighbor {link.overlay_vpn_ip} update-source {link.controller_vpn_ip}",
            f"neighbor {link.overlay_vpn_ip} route-map {route_map} in",
            f"route-map {route_map} permit 10",
            f"set local-preference {local_pref}",
            "end",
            "write memory",
        )
        logger.info("BGP: added neighbor %s/%s (%s)", node_name, link.kind.value, link.overlay_vpn_ip)
    except Exception as exc:
        logger.warning("BGP: could not add neighbor %s/%s: %s", node_name, link.kind.value, exc)


async def remove_neighbor(link: TransportLink, node_name: str) -> None:
    """Remove a transport link's BGP neighbor entry from the route reflector."""
    route_map = _route_map_name(link)
    try:
        await _vtysh(
            "configure terminal",
            f"router bgp {BGP_ASN}",
            f"no neighbor {link.overlay_vpn_ip}",
            f"no route-map {route_map} permit 10",
            "end",
            "write memory",
        )
        logger.info("BGP: removed neighbor %s/%s (%s)", node_name, link.kind.value, link.overlay_vpn_ip)
    except Exception as exc:
        logger.warning("BGP: could not remove neighbor %s/%s: %s", node_name, link.kind.value, exc)


def generate_node_config(node: Node) -> str:
    """Generate the FRR config for an edge node (fetched via GET /frr-config)."""
    active_links = sorted(
        [link for link in node.transport_links if link.wireguard_public_key and link.overlay_vpn_ip and link.controller_vpn_ip],
        key=lambda item: (item.priority, item.kind.value),
    )
    router_id = active_links[0].overlay_vpn_ip if active_links else node.vpn_ip
    lines = [
        "frr defaults traditional",
        f"hostname {node.name}",
        "log syslog informational",
        "!",
        "bfd",
    ]
    for link in active_links:
        lines += [
            f" peer {link.controller_vpn_ip} multihop local-address {link.overlay_vpn_ip}",
            " !",
        ]
    lines += [
        f"router bgp {BGP_ASN}",
        f" bgp router-id {router_id}",
        " no bgp default ipv4-unicast",
        " !",
    ]
    for link in active_links:
        lines += [
            f" neighbor {link.controller_vpn_ip} remote-as {BGP_ASN}",
            f" neighbor {link.controller_vpn_ip} update-source {link.interface_name or 'wg0'}",
            f" neighbor {link.controller_vpn_ip} bfd",
            " !",
        ]
    lines += [
        " address-family ipv4 unicast",
    ]
    for link in active_links:
        lines.append(f"  neighbor {link.controller_vpn_ip} activate")
        lines.append(f"  neighbor {link.controller_vpn_ip} soft-reconfiguration inbound")
    if node.site_subnet:
        lines.append(f"  network {node.site_subnet}")
    lines += [
        " exit-address-family",
        "!",
    ]
    return "\n".join(lines) + "\n"
