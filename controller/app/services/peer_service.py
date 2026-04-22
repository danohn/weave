from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Node, NodeStatus
from app.schemas.node import PeerResponse
from app.services.wireguard_service import get_public_key


async def get_peers(node: Node, session: AsyncSession) -> list[PeerResponse]:
    result = await session.execute(
        select(Node).where(
            Node.status == NodeStatus.ACTIVE,
            Node.id != node.id,
        )
    )
    peers = list(result.scalars().all())

    response = [
        PeerResponse(
            name=peer.name,
            wireguard_public_key=peer.wireguard_public_key,
            vpn_ip=peer.vpn_ip,
            preferred_endpoint=peer.reflected_endpoint_ip or peer.endpoint_ip,
            endpoint_port=peer.endpoint_port,
            nat_detected=(peer.reflected_endpoint_ip or peer.endpoint_ip) != peer.endpoint_ip,
            site_subnet=peer.site_subnet,
        )
        for peer in peers
    ]

    # Include the controller as a peer when WEAVE_DOMAIN is configured.
    # Agents already connect to this domain for the API — the same hostname
    # is used for the WireGuard endpoint (UDP instead of HTTPS).
    controller_pubkey = get_public_key()
    if controller_pubkey and settings.WEAVE_DOMAIN:
        response.append(
            PeerResponse(
                name="weave-rr",
                wireguard_public_key=controller_pubkey,
                vpn_ip=settings.CONTROLLER_VPN_IP,
                preferred_endpoint=settings.WEAVE_DOMAIN,
                endpoint_port=settings.CONTROLLER_ENDPOINT_PORT,
                nat_detected=False,
                site_subnet=None,
            )
        )

    return response
