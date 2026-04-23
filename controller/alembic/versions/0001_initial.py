"""initial schema

Revision ID: 0001
Revises:
Create Date: 2025-01-01 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "nodes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("wireguard_public_key", sa.String(), nullable=False),
        sa.Column("endpoint_ip", sa.String(), nullable=False),
        sa.Column("endpoint_port", sa.Integer(), nullable=False),
        sa.Column("reflected_endpoint_ip", sa.String(), nullable=True),
        sa.Column("reflected_endpoint_port", sa.Integer(), nullable=True),
        sa.Column("vpn_ip", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("PENDING", "ACTIVE", "REVOKED", name="nodestatus"),
            nullable=False,
        ),
        sa.Column(
            "last_seen",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("auth_token", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("auth_token"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("wireguard_public_key"),
    )
    op.create_index(op.f("ix_nodes_name"), "nodes", ["name"], unique=True)
    op.create_index(
        op.f("ix_nodes_wireguard_public_key"),
        "nodes",
        ["wireguard_public_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_nodes_wireguard_public_key"), table_name="nodes")
    op.drop_index(op.f("ix_nodes_name"), table_name="nodes")
    op.drop_table("nodes")
