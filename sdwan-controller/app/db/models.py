import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NodeStatus(str, enum.Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    OFFLINE = "OFFLINE"


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
    vpn_ip: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[NodeStatus] = mapped_column(
        Enum(NodeStatus), nullable=False, default=NodeStatus.PENDING
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    auth_token: Mapped[str] = mapped_column(String, unique=True, nullable=False)
