"""
WireGuard interface management via iproute2 and the wg CLI.

Interface lifecycle is handled with `ip link` / `ip addr`. Peer
synchronisation uses `wg syncconf`, which atomically replaces the peer
list on a live interface without tearing it down — existing sessions with
unchanged peers are unaffected.
"""

import logging
import os
import subprocess
import tempfile
from pathlib import Path

from agent.controller import Peer

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


def sync_peers(interface: str, peers: list[Peer]) -> None:
    """
    Atomically replace the full peer list using `wg syncconf`.

    syncconf applies only the diff between the current and desired state,
    so sessions with peers whose configuration has not changed are
    unaffected.
    """
    lines = []
    for peer in peers:
        lines += [
            "[Peer]",
            f"PublicKey = {peer.wireguard_public_key}",
            f"Endpoint = {peer.preferred_endpoint}:{peer.endpoint_port}",
            f"AllowedIPs = {peer.vpn_ip}/32",
            "PersistentKeepalive = 25",
            "",
        ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as f:
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
        (p.wireguard_public_key, p.preferred_endpoint, p.endpoint_port)
        for p in peers
    )
