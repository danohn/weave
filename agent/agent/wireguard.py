"""
WireGuard interface management via kernel UAPI and iproute2.

Replaces wg-quick with direct kernel communication:
  - Interface lifecycle via `ip link` / `ip addr` subprocesses
  - WireGuard keys and peers via the UAPI Unix socket at
    /var/run/wireguard/<interface>.sock

The key benefit over wg-quick is sync_peers(): it atomically replaces
the peer list without tearing the interface down, so existing sessions
with unchanged peers survive uninterrupted.
"""

import base64
import binascii
import logging
import socket as _socket
import subprocess
import time
from pathlib import Path

from agent.controller import Peer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _b64_to_hex(b64: str) -> str:
    """Base64-encoded WireGuard key → 64-char hex string required by UAPI."""
    return binascii.hexlify(base64.b64decode(b64)).decode()


def _run(cmd: list[str], input: str | None = None) -> str:
    result = subprocess.run(cmd, input=input, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{cmd[0]!r} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _interface_exists(interface: str) -> bool:
    return subprocess.run(
        ["ip", "link", "show", interface], capture_output=True
    ).returncode == 0


def _uapi(interface: str, msg: str) -> None:
    """
    Send a UAPI SET command to the WireGuard kernel socket and verify errno.

    The socket at /var/run/wireguard/<interface>.sock is created by the
    kernel module when the interface is added via netlink.  We retry briefly
    in case there is a small delay between `ip link add` and socket creation.
    """
    sock_path = Path(f"/var/run/wireguard/{interface}.sock")
    for _ in range(20):
        if sock_path.exists():
            break
        time.sleep(0.1)
    else:
        raise RuntimeError(f"UAPI socket not found: {sock_path}")

    with _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM) as s:
        s.connect(str(sock_path))
        s.sendall(msg.encode())
        buf = b""
        while not buf.endswith(b"\n\n"):
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk

    for line in buf.decode().splitlines():
        if line.startswith("errno=") and line != "errno=0":
            raise RuntimeError(f"WireGuard UAPI error on {interface!r}: {line}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

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
    Create and configure the WireGuard interface if not already present,
    then apply the private key and listen port via UAPI.

    Idempotent: safe to call on an interface that already exists (e.g. after
    an agent restart).  The interface and its VPN address persist across
    agent restarts so traffic continues during brief outages.
    """
    if not _interface_exists(interface):
        logger.info("Creating interface %s with address %s/24", interface, vpn_ip)
        _run(["ip", "link", "add", interface, "type", "wireguard"])
        _run(["ip", "addr", "add", f"{vpn_ip}/24", "dev", interface])
        _run(["ip", "link", "set", interface, "up"])
    else:
        logger.info("Interface %s already exists — reconfiguring", interface)
        _run(["ip", "link", "set", interface, "up"])

    private_key = Path(private_key_file).read_text().strip()
    _uapi(
        interface,
        f"set=1\nprivate_key={_b64_to_hex(private_key)}\nlisten_port={listen_port}\n\n",
    )
    logger.info("Interface %s configured (port %d)", interface, listen_port)


def sync_peers(interface: str, peers: list[Peer]) -> None:
    """
    Atomically replace the full peer list via UAPI — no interface teardown.

    replace_peers=true tells the kernel to remove any peer not mentioned in
    this message, so the result is always exactly *peers*.  Sessions with
    peers whose endpoint/keys have not changed are unaffected.
    """
    lines = ["set=1", "replace_peers=true"]
    for peer in peers:
        lines += [
            f"public_key={_b64_to_hex(peer.wireguard_public_key)}",
            f"endpoint={peer.preferred_endpoint}:{peer.endpoint_port}",
            f"allowed_ip={peer.vpn_ip}/32",
            "persistent_keepalive_interval=25",
        ]
    lines += ["", ""]  # UAPI message terminator (double newline)
    _uapi(interface, "\n".join(lines))
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
