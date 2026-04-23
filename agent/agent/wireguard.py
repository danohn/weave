"""
WireGuard interface management via iproute2 and the wg CLI.

Interface lifecycle is handled with `ip link` / `ip addr`. Peer
synchronisation uses `wg syncconf`, which atomically replaces the peer
list on a live interface without tearing it down — existing sessions with
unchanged peers are unaffected.
"""

import logging
import os
import socket
import subprocess
import tempfile
from pathlib import Path

from agent.controller import DestinationPolicy, Peer

logger = logging.getLogger(__name__)


def _run(cmd: list[str], input: str | None = None) -> str:
    result = subprocess.run(cmd, input=input, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{cmd[0]!r} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _interface_exists(interface: str) -> bool:
    return subprocess.run(
        ["ip", "link", "show", interface], capture_output=True
    ).returncode == 0


def _ip(*args: str) -> str:
    return _run(["ip", *args])


def _best_effort(cmd: list[str]) -> None:
    subprocess.run(cmd, capture_output=True, text=True)


def ensure_private_key(key_file: str) -> str:
    """
    Load private key from *key_file*, generating one if absent.
    Returns the corresponding base64 public key.
    """
    p = Path(key_file)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        private_key = _run(["wg", "genkey"])
        p.write_text(private_key + "\n")
        p.chmod(0o600)
        logger.info("Generated new WireGuard private key at %s", key_file)

    private_key = p.read_text().strip()
    result = subprocess.run(
        ["wg", "pubkey"], input=private_key, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"wg pubkey failed: {result.stderr.strip()}")
    return result.stdout.strip()


def setup_interface(
    interface: str,
    vpn_ip: str,
    private_key_file: str,
    listen_port: int,
) -> None:
    """
    Create and configure the WireGuard interface if not already present.

    Idempotent: safe to call on an interface that already exists (e.g. after
    an agent restart). The interface and its VPN address persist across agent
    restarts so traffic continues during brief outages.
    """
    if not _interface_exists(interface):
        logger.info("Creating interface %s with address %s/24", interface, vpn_ip)
        _run(["ip", "link", "add", interface, "type", "wireguard"])
        _run(["ip", "addr", "add", f"{vpn_ip}/24", "dev", interface])
    else:
        logger.info("Interface %s already exists — reconfiguring", interface)

    _run(["wg", "set", interface,
          "private-key", private_key_file,
          "listen-port", str(listen_port)])
    _run(["ip", "link", "set", interface, "up"])
    logger.info("Interface %s configured (port %d)", interface, listen_port)


def _resolve_host_ips(hostname: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_DGRAM)
    except socket.gaierror:
        return []
    return sorted({item[4][0] for item in infos})


def sync_underlay_routes(
    peers: list[Peer],
    *,
    transport_kind: str | None,
    bind_interface: str | None,
    source_ip: str | None,
    gateway: str | None,
) -> None:
    """Install transport underlay routing.

    For legacy or single-NIC agents, keep the old host-route behavior.
    When a transport has an explicit source IP, also program a dedicated
    routing table plus a source-based rule so locally generated WireGuard
    packets egress via the intended underlay NIC.
    """
    if not bind_interface:
        return
    table = _route_table_for_transport(transport_kind)
    if source_ip:
        subnet = ".".join(source_ip.split(".")[:3]) + ".0/24"
        _ip("route", "replace", subnet, "dev", bind_interface, "src", source_ip, "table", table)
        if gateway:
            _ip(
                "route",
                "replace",
                "default",
                "via",
                gateway,
                "dev",
                bind_interface,
                "src",
                source_ip,
                "table",
                table,
            )
        else:
            _ip("route", "replace", "default", "dev", bind_interface, "src", source_ip, "table", table)
        rule_priority = {
            "internet": "9001",
            "mpls": "9002",
            "lte": "9003",
            "other": "9004",
        }.get(transport_kind or "other", "9004")
        _best_effort(["ip", "rule", "del", "priority", rule_priority])
        _ip("rule", "add", "from", f"{source_ip}/32", "lookup", table, "priority", rule_priority)

    endpoints: set[str] = set()
    for peer in peers:
        host = peer.preferred_endpoint
        if not host:
            continue
        if host.replace(".", "").isdigit() and host.count(".") == 3:
            endpoints.add(host)
            continue
        endpoints.update(_resolve_host_ips(host))

    for endpoint_ip in sorted(endpoints):
        cmd = ["route", "replace", f"{endpoint_ip}/32"]
        if gateway:
            cmd += ["via", gateway]
        cmd += ["dev", bind_interface]
        if source_ip:
            cmd += ["src", source_ip]
        _ip(*cmd)
        if source_ip:
            table_cmd = ["route", "replace", f"{endpoint_ip}/32"]
            if gateway:
                table_cmd += ["via", gateway]
            table_cmd += ["dev", bind_interface, "src", source_ip, "table", table]
            _ip(*table_cmd)

    if source_ip:
        _best_effort(["ip", "route", "flush", "cache"])


def _route_table_for_transport(kind: str | None) -> str:
    return {
        "internet": "501",
        "mpls": "502",
        "lte": "503",
        "other": "504",
    }.get(kind or "other", "504")


def sync_destination_policy_routes(
    policies: list[DestinationPolicy],
    *,
    previous_rules: dict[str, tuple[str, str]] | None = None,
) -> dict[str, tuple[str, str]]:
    """Apply destination-prefix policy through transport-specific route tables."""
    current_rules: dict[str, tuple[str, str]] = {}
    for index, policy in enumerate(policies):
        rule_priority = str(10000 + index)
        if not policy.enabled or not policy.selected_interface or not policy.selected_transport:
            continue
        table = _route_table_for_transport(policy.selected_transport)
        _ip(
            "route",
            "replace",
            policy.destination_prefix,
            "dev",
            policy.selected_interface,
            "table",
            table,
            "metric",
            "25",
        )
        subprocess.run(
            ["ip", "rule", "del", "priority", rule_priority],
            capture_output=True,
            text=True,
        )
        _ip(
            "rule",
            "add",
            "to",
            policy.destination_prefix,
            "lookup",
            table,
            "priority",
            rule_priority,
        )
        current_rules[policy.destination_prefix] = (rule_priority, table)

    for prefix, (priority, table) in (previous_rules or {}).items():
        if prefix in current_rules:
            continue
        subprocess.run(
            ["ip", "rule", "del", "priority", priority],
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["ip", "route", "del", prefix, "table", table],
            capture_output=True,
            text=True,
        )
    return current_rules


def sync_peers(
    interface: str,
    peers: list[Peer],
    private_key_file: str,
    listen_port: int,
) -> None:
    """
    Atomically replace the full peer list using `wg syncconf`.

    syncconf applies only the diff between the current and desired state,
    so sessions with peers whose configuration has not changed are
    unaffected.

    The [Interface] section must be included in the syncconf file,
    otherwise syncconf treats the missing section as "empty" and resets
    the listen-port to a random ephemeral value.
    """
    private_key = Path(private_key_file).read_text().strip()
    lines = [
        "[Interface]",
        f"PrivateKey = {private_key}",
        f"ListenPort = {listen_port}",
        "",
    ]
    for peer in peers:
        allowed_ips = f"{(peer.overlay_vpn_ip or peer.vpn_ip)}/32"
        if peer.site_subnet:
            allowed_ips += f", {peer.site_subnet}"
        lines += [
            "[Peer]",
            f"PublicKey = {peer.wireguard_public_key}",
            f"Endpoint = {peer.preferred_endpoint}:{peer.endpoint_port}",
            f"AllowedIPs = {allowed_ips}",
            "PersistentKeepalive = 25",
            "",
        ]

    # Write to /etc/weave/ (mode 700) rather than /tmp so the private key
    # is never visible to other users even briefly.
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".conf", delete=False, dir="/etc/weave"
    ) as f:
        os.chmod(f.fileno(), 0o600)
        f.write("\n".join(lines))
        tmp = f.name
    try:
        _run(["wg", "syncconf", interface, tmp])
    finally:
        os.unlink(tmp)

    logger.debug("Synced %d peer(s) on %s", len(peers), interface)


def teardown(interface: str) -> None:
    """Remove the WireGuard interface (explicit clean shutdown only)."""
    if _interface_exists(interface):
        logger.info("Removing interface %s", interface)
        _run(["ip", "link", "del", interface])


def peer_signature(peers: list[Peer]) -> frozenset:
    """Hashable representation of a peer list for change detection."""
    return frozenset(
        (
            p.wireguard_public_key,
            p.overlay_vpn_ip or p.vpn_ip,
            p.preferred_endpoint,
            p.endpoint_port,
            p.site_subnet,
            p.transport_kind,
        )
        for p in peers
    )
