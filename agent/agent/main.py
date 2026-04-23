import asyncio
import json
import logging
import signal
import sys

from agent import frr
from agent import wireguard as wg
from agent.config import Settings
from agent.controller import ControllerClient, TransportLinkHeartbeat, parse_peer
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
    return [
        TransportLinkHeartbeat(
            name=settings.TRANSPORT_NAME,
            kind=settings.TRANSPORT_KIND,
            endpoint_port=settings.ENDPOINT_PORT,
            interface_name=settings.INTERFACE,
        )
    ]


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
    last_sig: frozenset = frozenset()

    def apply(peers: list) -> None:
        nonlocal last_sig
        sig = wg.peer_signature(peers)
        if sig != last_sig:
            logger.info("Peer list changed (%d peer(s)) — syncing", len(peers))
            wg.sync_peers(
                settings.INTERFACE, peers,
                settings.PRIVATE_KEY_FILE, settings.ENDPOINT_PORT,
            )
            last_sig = sig

    while True:
        try:
            async with client.peer_websocket(node.node_id, node.auth_token) as ws:
                logger.info("Connected to peer update stream")
                async for message in ws:
                    data = json.loads(message)
                    if data.get("type") == "ping":
                        await ws.send(json.dumps({"type": "pong"}))
                        continue
                    peers = [parse_peer(p) for p in data["peers"]]
                    apply(peers)

        except Exception as exc:
            logger.warning("Peer stream disconnected: %s — falling back to poll", exc)
            try:
                peers = await client.get_peers(node.node_id, node.auth_token)
                apply(peers)
            except Exception as poll_exc:
                logger.warning("Peer poll failed: %s", poll_exc)

        await asyncio.sleep(WS_RECONNECT_INTERVAL)


async def run() -> None:
    settings = Settings()
    client = ControllerClient(settings.CONTROLLER_URL)

    # Ensure WireGuard key exists and get public key
    public_key = wg.ensure_private_key(settings.PRIVATE_KEY_FILE)
    logger.info("WireGuard public key: %s", public_key)

    # Load existing state or register for the first time
    node = state_store.load(settings.STATE_FILE)
    if node is None:
        logger.info("No state found — registering with controller")
        resp = await client.register(
            name=settings.NODE_NAME,
            wireguard_public_key=public_key,
            endpoint_port=settings.ENDPOINT_PORT,
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
    peers: list = []
    for attempt in range(1, 11):
        try:
            peers = await client.get_peers(node.node_id, node.auth_token)
            break
        except Exception as exc:
            if attempt == 10:
                raise
            logger.warning(
                "Failed to fetch initial peer list (attempt %d/10): %s — retrying in 5s", attempt, exc
            )
            await asyncio.sleep(5)
    wg.setup_interface(
        interface=settings.INTERFACE,
        vpn_ip=node.vpn_ip,
        private_key_file=settings.PRIVATE_KEY_FILE,
        listen_port=settings.ENDPOINT_PORT,
    )
    wg.sync_peers(settings.INTERFACE, peers, settings.PRIVATE_KEY_FILE, settings.ENDPOINT_PORT)

    # Fetch and apply FRR BGP config (no-op if FRR is not installed)
    try:
        frr_config = await client.get_frr_config(node.node_id, node.auth_token)
        frr.apply_config(frr_config)
    except Exception as exc:
        logger.warning("Could not apply FRR config: %s", exc)

    logger.info("Interface %s is up — entering main loop", settings.INTERFACE)

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
