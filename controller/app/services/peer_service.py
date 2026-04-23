from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import controller_overlay_ip_for_kind, settings
from app.db.models import DestinationPolicy, Node, NodeStatus, TransportLink, TransportStatus
from app.schemas.node import OverlayConfigResponse, OverlayTransportConfig, PeerResponse
from app.services.policy_service import policy_applies_to_node, resolve_policy_for_node
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


async def get_overlay_config(node: Node, session: AsyncSession) -> OverlayConfigResponse:
    result = await session.execute(
        select(Node)
        .options(selectinload(Node.site), selectinload(Node.transport_links))
        .where(
            Node.status == NodeStatus.ACTIVE,
            Node.id != node.id,
        )
    )
    nodes = list(result.scalars().all())
    transports = sorted(
        [
            link
            for link in node.transport_links
            if link.admin_state_up
            and link.wireguard_public_key
            and link.overlay_vpn_ip
        ],
        key=lambda item: (item.priority, item.kind.value),
    )
    transport_by_kind: dict[str, TransportLink] = {link.kind.value: link for link in transports}
    peers: list[PeerResponse] = []
    for peer in nodes:
        peer_links = {
            link.kind.value: link
            for link in peer.transport_links
            if link.admin_state_up
            and link.wireguard_public_key
            and link.overlay_vpn_ip
        }
        for transport in transports:
            remote = peer_links.get(transport.kind.value)
            if remote is None:
                continue
            preferred_endpoint = remote.endpoint_ip or remote.reflected_endpoint_ip
            if not preferred_endpoint or not remote.endpoint_port:
                continue
            peers.append(
                PeerResponse(
                    name=f"{peer.name}-{transport.kind.value}",
                    wireguard_public_key=remote.wireguard_public_key,
                    vpn_ip=remote.overlay_vpn_ip,
                    overlay_vpn_ip=remote.overlay_vpn_ip,
                    preferred_endpoint=preferred_endpoint,
                    endpoint_port=remote.endpoint_port,
                    nat_detected=(remote.reflected_endpoint_ip or remote.endpoint_ip) != remote.endpoint_ip,
                    site_subnet=peer.site_subnet if remote.is_active else None,
                    site_id=peer.site_id,
                    site_name=peer.site.name if peer.site is not None else None,
                    transport_link_id=remote.id,
                    transport_kind=remote.kind,
                )
            )

    controller_pubkey = get_public_key()
    if controller_pubkey and settings.WEAVE_DOMAIN:
        for transport in transports:
            peers.append(
                PeerResponse(
                    name=f"weave-rr-{transport.kind.value}",
                    wireguard_public_key=controller_pubkey,
                    vpn_ip=transport.controller_vpn_ip or controller_overlay_ip_for_kind(transport.kind.value),
                    overlay_vpn_ip=transport.controller_vpn_ip or controller_overlay_ip_for_kind(transport.kind.value),
                    preferred_endpoint=settings.WEAVE_DOMAIN,
                    endpoint_port=settings.CONTROLLER_ENDPOINT_PORT,
                    nat_detected=False,
                    site_subnet=None,
                    transport_link_id=transport.id,
                    transport_kind=transport.kind,
                )
            )

    policy_result = await session.execute(
        select(DestinationPolicy)
        .where(DestinationPolicy.enabled.is_(True))
        .order_by(DestinationPolicy.priority.asc(), DestinationPolicy.created_at.asc())
    )
    policies = [item for item in policy_result.scalars().all() if policy_applies_to_node(item, node)]

    return OverlayConfigResponse(
        transports=[
            OverlayTransportConfig(
                interface_name=link.interface_name or "wg0",
                name=link.name,
                kind=link.kind,
                wireguard_public_key=link.wireguard_public_key,
                overlay_vpn_ip=link.overlay_vpn_ip,
                controller_vpn_ip=link.controller_vpn_ip or controller_overlay_ip_for_kind(link.kind.value),
                endpoint_port=link.endpoint_port or settings.CONTROLLER_ENDPOINT_PORT,
                priority=link.priority,
                is_active=link.is_active,
            )
            for link in transports
        ],
        peers=peers,
        destination_policies=[
            _resolve_destination_policy(node, policy)
            for policy in policies
        ],
    )


def _resolve_destination_policy(node: Node, policy: DestinationPolicy):
    resolved = resolve_policy_for_node(node, policy)
    selected = resolved["selected"]

    from app.schemas.node import DestinationPolicyResponse

    return DestinationPolicyResponse(
        id=policy.id,
        name=policy.name,
        destination_prefix=policy.destination_prefix,
        description=policy.description,
        site_id=policy.site_id,
        site_name=policy.site.name if getattr(policy, "site", None) is not None else None,
        node_id=policy.node_id,
        node_name=policy.node.name if getattr(policy, "node", None) is not None else None,
        preferred_transport=policy.preferred_transport,
        fallback_transport=policy.fallback_transport,
        selected_transport=selected.kind if selected is not None else None,
        selected_interface=selected.interface_name if selected is not None else None,
        priority=policy.priority,
        enabled=policy.enabled,
    )
