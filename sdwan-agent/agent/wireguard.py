import logging
import os
import subprocess
from pathlib import Path

from agent.controller import Peer

logger = logging.getLogger(__name__)


def ensure_private_key(key_file: str) -> str:
    """Load or generate a WireGuard private key. Returns the public key."""
    p = Path(key_file)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        private_key = _run(["wg", "genkey"]).stdout.strip()
        p.write_text(private_key)
        os.chmod(key_file, 0o600)
        logger.info("Generated new WireGuard private key at %s", key_file)

    private_key = p.read_text().strip()
    public_key = _run(["wg", "pubkey"], input=private_key).stdout.strip()
    return public_key


def write_config(
    config_file: str,
    vpn_ip: str,
    private_key_file: str,
    listen_port: int,
    peers: list[Peer],
) -> None:
    private_key = Path(private_key_file).read_text().strip()

    peer_blocks = []
    for peer in peers:
        peer_blocks.append(
            f"[Peer]\n"
            f"# {peer.name}\n"
            f"PublicKey = {peer.wireguard_public_key}\n"
            f"AllowedIPs = {peer.vpn_ip}/32\n"
            f"Endpoint = {peer.preferred_endpoint}:{peer.endpoint_port}\n"
            f"PersistentKeepalive = 25"
        )

    lines = [
        "[Interface]",
        f"Address = {vpn_ip}/24",
        f"PrivateKey = {private_key}",
        f"ListenPort = {listen_port}",
    ]
    if peer_blocks:
        lines += ["", *("\n\n".join(peer_blocks).splitlines())]

    p = Path(config_file)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n")
    os.chmod(config_file, 0o600)
    logger.debug("Wrote config to %s (%d peer(s))", config_file, len(peers))


def is_up(interface: str) -> bool:
    return subprocess.run(
        ["ip", "link", "show", interface],
        capture_output=True,
    ).returncode == 0


def up(interface: str) -> None:
    logger.info("Bringing up %s", interface)
    result = _run(["wg-quick", "up", interface])
    if result.returncode != 0:
        raise RuntimeError(f"wg-quick up failed:\n{result.stderr}")


def down(interface: str) -> None:
    logger.info("Bringing down %s", interface)
    _run(["wg-quick", "down", interface])


def reload(interface: str, config_file: str) -> None:
    """Tear down and bring up the interface to apply a changed peer list."""
    down(interface)
    up(interface)


def peer_signature(peers: list[Peer]) -> frozenset:
    """A hashable representation of a peer list for change detection."""
    return frozenset(
        (p.wireguard_public_key, p.preferred_endpoint, p.endpoint_port)
        for p in peers
    )


def _run(cmd: list[str], input: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, input=input, capture_output=True, text=True)
