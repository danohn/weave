from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DestinationPolicy
from app.schemas.node import (
    DestinationPolicyCreateRequest,
    DestinationPolicyUpdateRequest,
)


async def list_policies(session: AsyncSession) -> list[DestinationPolicy]:
    result = await session.execute(
        select(DestinationPolicy).order_by(
            DestinationPolicy.priority.asc(), DestinationPolicy.created_at.asc()
        )
    )
    return list(result.scalars().all())


async def create_policy(
    session: AsyncSession, data: DestinationPolicyCreateRequest
) -> DestinationPolicy:
    if data.site_id and data.node_id:
        raise HTTPException(
            status_code=400,
            detail="Policy scope must target either a site or a node, not both",
        )
    existing = await session.execute(
        select(DestinationPolicy).where(DestinationPolicy.name == data.name)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Policy name already exists")
    policy = DestinationPolicy(**data.model_dump())
    session.add(policy)
    await session.commit()
    await session.refresh(policy)
    return policy


async def update_policy(
    session: AsyncSession, policy_id: str, data: DestinationPolicyUpdateRequest
) -> DestinationPolicy:
    policy = await session.get(DestinationPolicy, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    changes = data.model_dump(exclude_unset=True)
    next_site_id = changes.get("site_id", policy.site_id)
    next_node_id = changes.get("node_id", policy.node_id)
    if next_site_id and next_node_id:
        raise HTTPException(
            status_code=400,
            detail="Policy scope must target either a site or a node, not both",
        )
    for key, value in changes.items():
        setattr(policy, key, value)
    await session.commit()
    await session.refresh(policy)
    return policy


async def delete_policy(session: AsyncSession, policy_id: str) -> None:
    policy = await session.get(DestinationPolicy, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    await session.delete(policy)
    await session.commit()
