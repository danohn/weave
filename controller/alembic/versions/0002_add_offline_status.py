"""add OFFLINE node status

Revision ID: 0002
Revises: 0001
Create Date: 2025-01-01 00:01:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_old_enum = sa.Enum("PENDING", "ACTIVE", "REVOKED", name="nodestatus")
_new_enum = sa.Enum("PENDING", "ACTIVE", "REVOKED", "OFFLINE", name="nodestatus")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # PostgreSQL supports adding enum values in-place (PG 9.1+)
        op.execute("ALTER TYPE nodestatus ADD VALUE IF NOT EXISTS 'OFFLINE'")
    else:
        # SQLite: recreate the table with the updated CHECK constraint
        with op.batch_alter_table("nodes") as batch_op:
            batch_op.alter_column(
                "status",
                existing_type=_old_enum,
                type_=_new_enum,
                existing_nullable=False,
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # PostgreSQL does not support removing enum values without a full
        # type recreation; skip silently and document the manual step.
        pass
    else:
        with op.batch_alter_table("nodes") as batch_op:
            batch_op.alter_column(
                "status",
                existing_type=_new_enum,
                type_=_old_enum,
                existing_nullable=False,
            )
