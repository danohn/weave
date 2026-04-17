"""add site_subnet to nodes

Revision ID: 0004
Revises: 0003
Create Date: 2025-01-01 00:03:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("nodes") as batch_op:
        batch_op.add_column(sa.Column("site_subnet", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("nodes") as batch_op:
        batch_op.drop_column("site_subnet")
