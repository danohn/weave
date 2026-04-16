import asyncio
import logging
import sys

from agent import wireguard as wg
from agent.config import Settings
from agent.controller import ControllerClient
from agent.state import NodeState
from agent import state as state_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def wait_until_active(
    client: ControllerClient,
    node: NodeState,
) -> None:
    """Poll heartbeat until the node is ACTIVE. Blocks until then."""
    while True:
        try:
            resp = await client.heartbeat(node.node_id, node.auth_token)
            if resp.status == "ACTIVE":
                logger.info("Node is ACTIVE")
                return
            if resp.status == "REVOKED":
                logger.error("Node has been revoked — exiting")
                sys.exit(1)
            logger.info("Status is %s — waiting for admin to activate...", resp.status)
        except Exception as exc:
            logger.warning("Could not reach controller: %s", exc)
        await asyncio.sleep(10)


async def heartbeat_loop(client: ControllerClient, node: NodeState, interval: int) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            resp = await client.heartbeat(node.node_id, node.auth_token)
            logger.debug("Heartbeat ok — status=%s", resp.status)
            if resp.status == "REVOKED":
                logger.error("Node has been revoked — exiting")
                sys.exit(1)
        except Exception as exc:
            logger.warning("Heartbeat failed: %s", exc)


async def peer_loop(
    client: ControllerClient,
    node: NodeState,
    settings: Settings,
) -> None:
    last_sig: frozenset = frozenset()

    while True:
        try:
            peers = await client.get_peers(node.node_id, node.auth_token)
            sig = wg.peer_signature(peers)

            if sig != last_sig:
                logger.info("Peer list changed (%d peer(s)) — reloading", len(peers))
                wg.write_config(
                    config_file=settings.wg_config_file,
                    vpn_ip=node.vpn_ip,
                    private_key_file=settings.PRIVATE_KEY_FILE,
                    listen_port=settings.ENDPOINT_PORT,
                    peers=peers,
                )
                if wg.is_up(settings.INTERFACE):
                    wg.reload(settings.INTERFACE, settings.wg_config_file)
                last_sig = sig
            else:
                logger.debug("Peer list unchanged (%d peer(s))", len(peers))

        except Exception as exc:
            logger.warning("Peer poll failed: %s", exc)

        await asyncio.sleep(settings.PEER_POLL_INTERVAL)


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
            endpoint_ip=settings.ENDPOINT_IP,
            endpoint_port=settings.ENDPOINT_PORT,
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
    await wait_until_active(client, node)

    # Fetch initial peer list and bring up the interface
    peers = await client.get_peers(node.node_id, node.auth_token)
    wg.write_config(
        config_file=settings.wg_config_file,
        vpn_ip=node.vpn_ip,
        private_key_file=settings.PRIVATE_KEY_FILE,
        listen_port=settings.ENDPOINT_PORT,
        peers=peers,
    )

    if wg.is_up(settings.INTERFACE):
        wg.down(settings.INTERFACE)
    wg.up(settings.INTERFACE)

    logger.info("Interface %s is up — entering main loop", settings.INTERFACE)

    await asyncio.gather(
        heartbeat_loop(client, node, settings.HEARTBEAT_INTERVAL),
        peer_loop(client, node, settings),
    )


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Shutting down")
