"""add unique constraint on node vpn_ip

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-23 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    duplicates = bind.execute(
        sa.text(
            """
            SELECT vpn_ip
            FROM nodes
            GROUP BY vpn_ip
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()
    if duplicates:
        raise RuntimeError(
            "Cannot add unique constraint to nodes.vpn_ip while duplicate VPN IPs exist"
        )

    with op.batch_alter_table("nodes") as batch_op:
        batch_op.create_unique_constraint("uq_nodes_vpn_ip", ["vpn_ip"])


def downgrade() -> None:
    with op.batch_alter_table("nodes") as batch_op:
        batch_op.drop_constraint("uq_nodes_vpn_ip", type_="unique")
