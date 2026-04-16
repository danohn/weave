from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Node, NodeStatus
from app.schemas.node import PeerResponse


async def get_peers(node: Node, session: AsyncSession) -> list[PeerResponse]:
    result = await session.execute(
        select(Node).where(
            Node.status == NodeStatus.ACTIVE,
            Node.id != node.id,
        )
    )
    peers = list(result.scalars().all())

    peer_responses: list[PeerResponse] = []
    for peer in peers:
        nat_detected = (
            peer.reflected_endpoint_ip is not None
            and peer.reflected_endpoint_ip != peer.endpoint_ip
        )
        preferred_endpoint = (
            peer.reflected_endpoint_ip if nat_detected else peer.endpoint_ip
        )
        peer_responses.append(
            PeerResponse(
                name=peer.name,
                wireguard_public_key=peer.wireguard_public_key,
                vpn_ip=peer.vpn_ip,
                preferred_endpoint=preferred_endpoint,
                endpoint_port=peer.endpoint_port,
                nat_detected=nat_detected,
            )
        )

    return peer_responses
