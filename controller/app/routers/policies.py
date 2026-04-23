from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent_ws import broadcast_peers
from app.core.security import require_admin
from app.db.base import get_session
from app.schemas.node import (
    DestinationPolicyCreateRequest,
    DestinationPolicyResponse,
    DestinationPolicyUpdateRequest,
)
from app.services import policy_service

router = APIRouter(prefix="/api/v1/policies", tags=["policies"])


def _to_response(policy) -> DestinationPolicyResponse:
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
        selected_transport=None,
        selected_interface=None,
        priority=policy.priority,
        enabled=policy.enabled,
    )


@router.get("/", response_model=list[DestinationPolicyResponse])
async def list_policies(
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_admin),
) -> list[DestinationPolicyResponse]:
    return [_to_response(item) for item in await policy_service.list_policies(session)]


@router.post("/", response_model=DestinationPolicyResponse, status_code=201)
async def create_policy(
    data: DestinationPolicyCreateRequest,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_admin),
) -> DestinationPolicyResponse:
    policy = await policy_service.create_policy(session, data)
    await broadcast_peers(session)
    return _to_response(policy)


@router.patch("/{policy_id}", response_model=DestinationPolicyResponse)
async def update_policy(
    policy_id: str,
    data: DestinationPolicyUpdateRequest,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_admin),
) -> DestinationPolicyResponse:
    policy = await policy_service.update_policy(session, policy_id, data)
    await broadcast_peers(session)
    return _to_response(policy)


@router.delete("/{policy_id}", status_code=204)
async def delete_policy(
    policy_id: str,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_admin),
) -> None:
    await policy_service.delete_policy(session, policy_id)
    await broadcast_peers(session)
