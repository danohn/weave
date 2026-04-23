"""add sites and transport links

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-23 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sites",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sites_name", "sites", ["name"], unique=True)

    op.create_table(
        "site_prefixes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("site_id", sa.String(), nullable=False),
        sa.Column("prefix", sa.String(), nullable=False),
        sa.Column("advertise", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_site_prefixes_site_id", "site_prefixes", ["site_id"], unique=False)

    op.create_table(
        "transport_links",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("node_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.Enum("INTERNET", "MPLS", "LTE", "OTHER", name="transportkind"), nullable=False),
        sa.Column("admin_state_up", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("endpoint_ip", sa.String(), nullable=True),
        sa.Column("endpoint_port", sa.Integer(), nullable=True),
        sa.Column("reflected_endpoint_ip", sa.String(), nullable=True),
        sa.Column("reflected_endpoint_port", sa.Integer(), nullable=True),
        sa.Column("rtt_ms", sa.Integer(), nullable=True),
        sa.Column("jitter_ms", sa.Integer(), nullable=True),
        sa.Column("loss_pct", sa.Integer(), nullable=True),
        sa.Column("status", sa.Enum("UNKNOWN", "HEALTHY", "DEGRADED", "DOWN", name="transportstatus"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("interface_name", sa.String(), nullable=True),
        sa.Column("last_reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transport_links_node_id", "transport_links", ["node_id"], unique=False)

    with op.batch_alter_table("nodes") as batch_op:
        batch_op.add_column(sa.Column("site_id", sa.String(), nullable=True))
        batch_op.create_index("ix_nodes_site_id", ["site_id"], unique=False)
        batch_op.create_foreign_key("fk_nodes_site_id", "sites", ["site_id"], ["id"])

    bind = op.get_bind()
    metadata = sa.MetaData()
    sites = sa.Table("sites", metadata, autoload_with=bind)
    site_prefixes = sa.Table("site_prefixes", metadata, autoload_with=bind)
    transport_links = sa.Table("transport_links", metadata, autoload_with=bind)
    nodes = sa.Table("nodes", metadata, autoload_with=bind)

    rows = bind.execute(
        sa.select(
            nodes.c.id,
            nodes.c.name,
            nodes.c.site_subnet,
            nodes.c.endpoint_ip,
            nodes.c.endpoint_port,
            nodes.c.reflected_endpoint_ip,
            nodes.c.reflected_endpoint_port,
        )
    ).fetchall()

    for row in rows:
        site_id = row.id
        bind.execute(
            sites.insert().values(id=site_id, name=row.name, description=None)
        )
        bind.execute(nodes.update().where(nodes.c.id == row.id).values(site_id=site_id))
        if row.site_subnet:
            bind.execute(
                site_prefixes.insert().values(
                    site_id=site_id,
                    prefix=row.site_subnet,
                    advertise=True,
                    priority=100,
                )
            )
        bind.execute(
            transport_links.insert().values(
                node_id=row.id,
                name="wan1",
                kind="INTERNET",
                admin_state_up=True,
                endpoint_ip=row.endpoint_ip,
                endpoint_port=row.endpoint_port,
                reflected_endpoint_ip=row.reflected_endpoint_ip,
                reflected_endpoint_port=row.reflected_endpoint_port,
                status="UNKNOWN",
                is_active=True,
                priority=100,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("nodes") as batch_op:
        batch_op.drop_constraint("fk_nodes_site_id", type_="foreignkey")
        batch_op.drop_index("ix_nodes_site_id")
        batch_op.drop_column("site_id")

    op.drop_index("ix_transport_links_node_id", table_name="transport_links")
    op.drop_table("transport_links")
    op.drop_index("ix_site_prefixes_site_id", table_name="site_prefixes")
    op.drop_table("site_prefixes")
    op.drop_index("ix_sites_name", table_name="sites")
    op.drop_table("sites")

    sa.Enum(name="transportstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="transportkind").drop(op.get_bind(), checkfirst=True)
