import asyncio
from collections import defaultdict
import json
import logging
import signal
import sys

from agent import frr
from agent import wireguard as wg
from agent.config import Settings, TransportConfig
from agent.controller import (
    ControllerClient,
    OverlayConfig,
    Peer,
    TransportLinkHeartbeat,
    parse_overlay_config,
    parse_peer,
)
from agent.state import NodeState
from agent import state as state_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    force=True,  # replace any handlers added by imported libraries
)
# Silence noisy third-party request logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def wait_until_active(
    client: ControllerClient,
    node: NodeState,
    settings: Settings,
) -> None:
    """Poll heartbeat until the node is ACTIVE. Blocks until then."""
    while True:
        try:
            resp = await client.heartbeat(
                node.node_id,
                node.auth_token,
                transport_links=_transport_reports(settings),
            )
            if resp.status == "ACTIVE":
                logger.info("Node is ACTIVE")
                return
            if resp.status == "REVOKED":
                logger.error("Node has been revoked — exiting")
                sys.exit(0)
            logger.info("Status is %s — waiting for admin to activate...", resp.status)
        except Exception as exc:
            logger.warning("Could not reach controller: %s", exc)
        await asyncio.sleep(10)


async def heartbeat_loop(
    client: ControllerClient,
    node: NodeState,
    settings: Settings,
    interval: int,
) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            resp = await client.heartbeat(
                node.node_id,
                node.auth_token,
                transport_links=_transport_reports(settings),
            )
            logger.debug("Heartbeat ok — status=%s", resp.status)
            if resp.status == "REVOKED":
                logger.error("Node has been revoked — exiting")
                sys.exit(0)
        except Exception as exc:
            logger.warning("Heartbeat failed: %s", exc)


def _transport_reports(settings: Settings) -> list[TransportLinkHeartbeat]:
    reports: list[TransportLinkHeartbeat] = []
    for transport in settings.transport_configs():
        reports.append(
            TransportLinkHeartbeat(
                name=transport.name,
                kind=transport.kind,
                wireguard_public_key=wg.ensure_private_key(transport.private_key_file),
                endpoint_port=transport.endpoint_port,
                interface_name=transport.interface,
            )
        )
    return reports


def _transport_config_by_kind(settings: Settings) -> dict[str, TransportConfig]:
    return {item.kind: item for item in settings.transport_configs()}


def _apply_overlay_config(settings: Settings, overlay: OverlayConfig) -> None:
    transport_by_kind = _transport_config_by_kind(settings)
    peers_by_kind: dict[str, list[Peer]] = defaultdict(list)
    for peer in overlay.peers:
        peers_by_kind[peer.transport_kind or "internet"].append(peer)

    for transport in overlay.transports:
        local = transport_by_kind.get(transport.kind)
        if local is None:
            logger.warning("Controller returned transport %s but agent is not configured for it", transport.kind)
            continue
        wg.setup_interface(
            interface=local.interface,
            vpn_ip=transport.overlay_vpn_ip,
            private_key_file=local.private_key_file,
            listen_port=local.endpoint_port,
        )
        wg.sync_underlay_routes(
            peers_by_kind.get(transport.kind, []),
            bind_interface=local.bind_interface,
            source_ip=local.source_ip,
            gateway=local.gateway,
        )
        wg.sync_peers(
            local.interface,
            peers_by_kind.get(transport.kind, []),
            local.private_key_file,
            local.endpoint_port,
        )
    _apply_overlay_config.previous_policy_rules = wg.sync_destination_policy_routes(
        overlay.destination_policies,
        previous_rules=getattr(_apply_overlay_config, "previous_policy_rules", {}),
    )


WS_RECONNECT_INTERVAL = 5  # seconds between WebSocket reconnect attempts


async def peer_loop(
    client: ControllerClient,
    node: NodeState,
    settings: Settings,
) -> None:
    """
    Maintain an up-to-date peer list via a persistent WebSocket connection.

    The controller pushes a new peer list whenever topology changes (node
    joins, leaves, goes offline, etc.).  If the WebSocket drops, we fall
    back to a single HTTP poll and then retry the connection after
    WS_RECONNECT_INTERVAL seconds.
    """
    last_sig_by_kind: dict[str, frozenset] = {}
    transport_by_kind = _transport_config_by_kind(settings)

    def apply(peers: list[Peer]) -> None:
        grouped: dict[str, list[Peer]] = defaultdict(list)
        for peer in peers:
            grouped[peer.transport_kind or "internet"].append(peer)
        for kind, local in transport_by_kind.items():
            transport_peers = grouped.get(kind, [])
            sig = wg.peer_signature(transport_peers)
            if sig == last_sig_by_kind.get(kind):
                continue
            logger.info("Peer list changed for %s (%d peer(s)) — syncing", kind, len(transport_peers))
            wg.sync_peers(local.interface, transport_peers, local.private_key_file, local.endpoint_port)
            last_sig_by_kind[kind] = sig

    while True:
        try:
            async with client.peer_websocket(node.node_id, node.auth_token) as ws:
                logger.info("Connected to peer update stream")
                async for message in ws:
                    data = json.loads(message)
                    if data.get("type") == "ping":
                        await ws.send(json.dumps({"type": "pong"}))
                        continue
                    if "transports" in data:
                        overlay = parse_overlay_config(data)
                        _apply_overlay_config(settings, overlay)
                        apply(overlay.peers)
                        continue
                    peers = [parse_peer(p) for p in data["peers"]]
                    apply(peers)

        except Exception as exc:
            logger.warning("Peer stream disconnected: %s — falling back to poll", exc)
            try:
                overlay = await client.get_overlay_config(node.node_id, node.auth_token)
                _apply_overlay_config(settings, overlay)
                apply(overlay.peers)
            except Exception as poll_exc:
                logger.warning("Peer poll failed: %s", poll_exc)

        await asyncio.sleep(WS_RECONNECT_INTERVAL)


async def run() -> None:
    settings = Settings()
    client = ControllerClient(settings.CONTROLLER_URL)
    transports = settings.transport_configs()

    # Ensure WireGuard key exists and get public key
    public_key = wg.ensure_private_key(transports[0].private_key_file)
    logger.info("WireGuard public key: %s", public_key)

    # Load existing state or register for the first time
    node = state_store.load(settings.STATE_FILE)
    if node is None:
        logger.info("No state found — registering with controller")
        resp = await client.register(
            name=settings.NODE_NAME,
            wireguard_public_key=public_key,
            endpoint_port=transports[0].endpoint_port,
            claim_token=settings.CLAIM_TOKEN or settings.PREAUTH_TOKEN,
        )
        node = NodeState(
            node_id=resp.id,
            auth_token=resp.auth_token,
            vpn_ip=resp.vpn_ip,
        )
        state_store.save(settings.STATE_FILE, node)
        logger.info(
            "Registered as '%s' — VPN IP %s — waiting for activation",
            settings.NODE_NAME,
            node.vpn_ip,
        )
    else:
        logger.info(
            "Loaded existing state — node_id=%s vpn_ip=%s",
            node.node_id,
            node.vpn_ip,
        )

    # Block until an admin activates the node
    await wait_until_active(client, node, settings)

    # Bring up the interface and load the initial peer list (with retry)
    overlay: OverlayConfig | None = None
    for attempt in range(1, 11):
        try:
            overlay = await client.get_overlay_config(node.node_id, node.auth_token)
            break
        except Exception as exc:
            if attempt == 10:
                raise
            logger.warning(
                "Failed to fetch initial overlay config (attempt %d/10): %s — retrying in 5s", attempt, exc
            )
            await asyncio.sleep(5)
    if overlay is None:
        raise RuntimeError("Controller did not return overlay config")
    _apply_overlay_config(settings, overlay)

    # Fetch and apply FRR BGP config (no-op if FRR is not installed)
    try:
        frr_config = await client.get_frr_config(node.node_id, node.auth_token)
        frr.apply_config(frr_config)
    except Exception as exc:
        logger.warning("Could not apply FRR config: %s", exc)

    logger.info("Configured %d transport interface(s) — entering main loop", len(overlay.transports))

    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _on_sigterm() -> None:
        logger.info("Received SIGTERM — initiating graceful shutdown")
        shutdown_event.set()

    loop.add_signal_handler(signal.SIGTERM, _on_sigterm)

    async def _shutdown_watcher() -> None:
        await shutdown_event.wait()
        try:
            await client.go_offline(node.node_id, node.auth_token)
            logger.info("Controller notified — node marked OFFLINE")
        except Exception as exc:
            logger.warning("Could not notify controller of shutdown: %s", exc)
        # Cancel all sibling tasks so gather() returns cleanly
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task():
                task.cancel()

    await asyncio.gather(
        heartbeat_loop(client, node, settings, settings.HEARTBEAT_INTERVAL),
        peer_loop(client, node, settings),
        _shutdown_watcher(),
        return_exceptions=True,
    )
    await client.aclose()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Shutting down")
