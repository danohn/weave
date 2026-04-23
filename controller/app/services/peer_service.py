from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.models import Node, NodeStatus
from app.schemas.node import PeerResponse
from app.services.wireguard_service import get_public_key


async def get_peers(node: Node, session: AsyncSession) -> list[PeerResponse]:
    result = await session.execute(
        select(Node)
        .options(selectinload(Node.site), selectinload(Node.transport_links))
        .where(
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
            preferred_endpoint=(
                next(
                    (
                        link.reflected_endpoint_ip or link.endpoint_ip
                        for link in peer.transport_links
                        if link.is_active and (link.reflected_endpoint_ip or link.endpoint_ip)
                    ),
                    None,
                )
                or peer.reflected_endpoint_ip
                or peer.endpoint_ip
            ),
            endpoint_port=(
                next(
                    (
                        link.endpoint_port
                        for link in peer.transport_links
                        if link.is_active and link.endpoint_port is not None
                    ),
                    None,
                )
                or peer.endpoint_port
            ),
            nat_detected=(peer.reflected_endpoint_ip or peer.endpoint_ip) != peer.endpoint_ip,
            site_subnet=peer.site_subnet,
            site_id=peer.site_id,
            site_name=peer.site.name if peer.site is not None else None,
            transport_link_id=next((link.id for link in peer.transport_links if link.is_active), None),
            transport_kind=next((link.kind for link in peer.transport_links if link.is_active), None),
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
