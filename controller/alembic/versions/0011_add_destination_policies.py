"""add destination policies

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "destination_policies",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("destination_prefix", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "preferred_transport",
            sa.Enum("INTERNET", "MPLS", "LTE", "OTHER", name="transportkind"),
            nullable=False,
        ),
        sa.Column(
            "fallback_transport",
            sa.Enum("INTERNET", "MPLS", "LTE", "OTHER", name="transportkind"),
            nullable=True,
        ),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_destination_policies_name"),
        "destination_policies",
        ["name"],
        unique=True,
    )
    op.create_index(
        op.f("ix_destination_policies_destination_prefix"),
        "destination_policies",
        ["destination_prefix"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_destination_policies_destination_prefix"),
        table_name="destination_policies",
    )
    op.drop_index(
        op.f("ix_destination_policies_name"), table_name="destination_policies"
    )
    op.drop_table("destination_policies")
