"""scope destination policies

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("destination_policies", sa.Column("site_id", sa.String(), nullable=True))
    op.add_column("destination_policies", sa.Column("node_id", sa.String(), nullable=True))
    op.create_index(op.f("ix_destination_policies_site_id"), "destination_policies", ["site_id"], unique=False)
    op.create_index(op.f("ix_destination_policies_node_id"), "destination_policies", ["node_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_destination_policies_node_id"), table_name="destination_policies")
    op.drop_index(op.f("ix_destination_policies_site_id"), table_name="destination_policies")
    op.drop_column("destination_policies", "node_id")
    op.drop_column("destination_policies", "site_id")
