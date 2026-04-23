"""add site events

Revision ID: 0013
Revises: 0012
Create Date: 2026-04-23 15:45:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "site_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "NODE_REGISTERED",
                "NODE_ACTIVATED",
                "NODE_OFFLINE",
                "NODE_REVOKED",
                "TRANSPORT_STATUS_CHANGED",
                "TRANSPORT_FAILOVER",
                "BGP_SESSION_ESTABLISHED",
                "BGP_SESSION_LOST",
                "POLICY_FALLBACK_ACTIVE",
                name="eventkind",
            ),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.Enum("INFO", "WARN", "CRITICAL", name="eventseverity"),
            nullable=False,
        ),
        sa.Column("node_id", sa.String(), nullable=True),
        sa.Column("site_id", sa.String(), nullable=True),
        sa.Column("transport_link_id", sa.String(), nullable=True),
        sa.Column(
            "transport_kind",
            sa.Enum("INTERNET", "MPLS", "LTE", "OTHER", name="transportkind"),
            nullable=True,
        ),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"]),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"]),
        sa.ForeignKeyConstraint(["transport_link_id"], ["transport_links.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_site_events_kind", "site_events", ["kind"], unique=False)
    op.create_index("ix_site_events_node_id", "site_events", ["node_id"], unique=False)
    op.create_index("ix_site_events_site_id", "site_events", ["site_id"], unique=False)
    op.create_index("ix_site_events_transport_link_id", "site_events", ["transport_link_id"], unique=False)
    op.create_index("ix_site_events_occurred_at", "site_events", ["occurred_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_site_events_occurred_at", table_name="site_events")
    op.drop_index("ix_site_events_transport_link_id", table_name="site_events")
    op.drop_index("ix_site_events_site_id", table_name="site_events")
    op.drop_index("ix_site_events_node_id", table_name="site_events")
    op.drop_index("ix_site_events_kind", table_name="site_events")
    op.drop_table("site_events")
