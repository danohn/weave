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

    return [
        PeerResponse(
            name=peer.name,
            wireguard_public_key=peer.wireguard_public_key,
            vpn_ip=peer.vpn_ip,
            preferred_endpoint=peer.reflected_endpoint_ip or peer.endpoint_ip,
            endpoint_port=peer.endpoint_port,
        )
        for peer in peers
    ]
