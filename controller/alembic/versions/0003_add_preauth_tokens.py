"""add preauth_tokens table

Revision ID: 0003
Revises: 0002
Create Date: 2025-01-01 00:02:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "preauth_tokens",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_by_node_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["used_by_node_id"], ["nodes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_preauth_tokens_token", "preauth_tokens", ["token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_preauth_tokens_token", table_name="preauth_tokens")
    op.drop_table("preauth_tokens")
