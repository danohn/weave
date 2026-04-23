import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

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


class TransportKind(str, enum.Enum):
    INTERNET = "internet"
    MPLS = "mpls"
    LTE = "lte"
    OTHER = "other"


class TransportStatus(str, enum.Enum):
    UNKNOWN = "UNKNOWN"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    nodes: Mapped[list["Node"]] = relationship(back_populates="site", lazy="selectin")
    prefixes: Mapped[list["SitePrefix"]] = relationship(
        back_populates="site",
        cascade="all, delete-orphan",
        order_by="SitePrefix.priority",
        lazy="selectin",
    )


class SitePrefix(Base):
    __tablename__ = "site_prefixes"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    site_id: Mapped[str] = mapped_column(
        String, ForeignKey("sites.id"), nullable=False, index=True
    )
    prefix: Mapped[str] = mapped_column(String, nullable=False)
    advertise: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    site: Mapped["Site"] = relationship(back_populates="prefixes", lazy="selectin")


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
    site_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("sites.id"), nullable=True, index=True
    )

    site: Mapped[Site | None] = relationship(back_populates="nodes", lazy="selectin")
    transport_links: Mapped[list["TransportLink"]] = relationship(
        back_populates="node",
        cascade="all, delete-orphan",
        order_by="TransportLink.priority",
        lazy="selectin",
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


class TransportLink(Base):
    __tablename__ = "transport_links"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    node_id: Mapped[str] = mapped_column(
        String, ForeignKey("nodes.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[TransportKind] = mapped_column(
        Enum(TransportKind), nullable=False, default=TransportKind.INTERNET
    )
    admin_state_up: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    endpoint_ip: Mapped[str | None] = mapped_column(String, nullable=True)
    endpoint_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reflected_endpoint_ip: Mapped[str | None] = mapped_column(String, nullable=True)
    reflected_endpoint_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rtt_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    jitter_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    loss_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[TransportStatus] = mapped_column(
        Enum(TransportStatus), nullable=False, default=TransportStatus.UNKNOWN
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    interface_name: Mapped[str | None] = mapped_column(String, nullable=True)
    last_reported_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    node: Mapped[Node] = relationship(back_populates="transport_links", lazy="selectin")
