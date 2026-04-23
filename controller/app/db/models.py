import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NodeStatus(str, enum.Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    OFFLINE = "OFFLINE"


class DeviceClaimStatus(str, enum.Enum):
    UNCLAIMED = "UNCLAIMED"
    CLAIMED = "CLAIMED"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class Node(Base):
    __tablename__ = "nodes"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    wireguard_public_key: Mapped[str] = mapped_column(
        String, unique=True, nullable=False, index=True
    )
    endpoint_ip: Mapped[str] = mapped_column(String, nullable=False)
    endpoint_port: Mapped[int] = mapped_column(Integer, nullable=False)
    reflected_endpoint_ip: Mapped[str | None] = mapped_column(String, nullable=True)
    reflected_endpoint_port: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    vpn_ip: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    site_subnet: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[NodeStatus] = mapped_column(
        Enum(NodeStatus), nullable=False, default=NodeStatus.PENDING
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    auth_token_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    auth_token_prefix: Mapped[str] = mapped_column(String, nullable=False, index=True)
    auth_token_issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    device_claim_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("device_claims.id"), nullable=True
    )


class DeviceClaim(Base):
    __tablename__ = "device_claims"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    device_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    site_name: Mapped[str | None] = mapped_column(String, nullable=True)
    expected_name: Mapped[str | None] = mapped_column(String, nullable=True)
    site_subnet: Mapped[str | None] = mapped_column(String, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[DeviceClaimStatus] = mapped_column(
        Enum(DeviceClaimStatus), nullable=False, default=DeviceClaimStatus.UNCLAIMED
    )
    token_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    token_prefix: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_by_node_id: Mapped[str | None] = mapped_column(String, nullable=True)
