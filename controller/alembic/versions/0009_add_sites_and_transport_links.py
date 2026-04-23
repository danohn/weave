"""add sites and transport links

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-23 00:00:00.000000

"""

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_names() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def _column_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    tables = _table_names()
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    if "sites" not in tables:
        op.create_table(
            "sites",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("description", sa.String(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
        )
    if "ix_sites_name" not in _index_names("sites"):
        op.create_index("ix_sites_name", "sites", ["name"], unique=True)

    if "site_prefixes" not in tables:
        op.create_table(
            "site_prefixes",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("site_id", sa.String(), nullable=False),
            sa.Column("prefix", sa.String(), nullable=False),
            sa.Column(
                "advertise", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["site_id"], ["sites.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if "ix_site_prefixes_site_id" not in _index_names("site_prefixes"):
        op.create_index(
            "ix_site_prefixes_site_id", "site_prefixes", ["site_id"], unique=False
        )

    if "transport_links" not in tables:
        op.create_table(
            "transport_links",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("node_id", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column(
                "kind",
                sa.Enum("INTERNET", "MPLS", "LTE", "OTHER", name="transportkind"),
                nullable=False,
            ),
            sa.Column(
                "admin_state_up", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
            sa.Column("endpoint_ip", sa.String(), nullable=True),
            sa.Column("endpoint_port", sa.Integer(), nullable=True),
            sa.Column("reflected_endpoint_ip", sa.String(), nullable=True),
            sa.Column("reflected_endpoint_port", sa.Integer(), nullable=True),
            sa.Column("rtt_ms", sa.Integer(), nullable=True),
            sa.Column("jitter_ms", sa.Integer(), nullable=True),
            sa.Column("loss_pct", sa.Integer(), nullable=True),
            sa.Column(
                "status",
                sa.Enum(
                    "UNKNOWN", "HEALTHY", "DEGRADED", "DOWN", name="transportstatus"
                ),
                nullable=False,
            ),
            sa.Column(
                "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("interface_name", sa.String(), nullable=True),
            sa.Column("last_reported_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["node_id"], ["nodes.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if "ix_transport_links_node_id" not in _index_names("transport_links"):
        op.create_index(
            "ix_transport_links_node_id", "transport_links", ["node_id"], unique=False
        )

    if is_sqlite:
        if "_alembic_tmp_nodes" in _table_names():
            op.execute("DROP TABLE _alembic_tmp_nodes")
        node_columns = _column_names("nodes")
        if "site_id" not in node_columns:
            op.add_column("nodes", sa.Column("site_id", sa.String(), nullable=True))
        if "ix_nodes_site_id" not in _index_names("nodes"):
            op.create_index("ix_nodes_site_id", "nodes", ["site_id"], unique=False)
    else:
        node_columns = _column_names("nodes")
        node_indexes = _index_names("nodes")
        with op.batch_alter_table("nodes") as batch_op:
            if "site_id" not in node_columns:
                batch_op.add_column(sa.Column("site_id", sa.String(), nullable=True))
            if "ix_nodes_site_id" not in node_indexes:
                batch_op.create_index("ix_nodes_site_id", ["site_id"], unique=False)
            if "site_id" not in node_columns:
                batch_op.create_foreign_key(
                    "fk_nodes_site_id", "sites", ["site_id"], ["id"]
                )

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

    existing_site_ids = {
        row[0] for row in bind.execute(sa.select(sites.c.id)).fetchall()
    }
    existing_prefix_keys = {
        (row[0], row[1])
        for row in bind.execute(
            sa.select(site_prefixes.c.site_id, site_prefixes.c.prefix)
        ).fetchall()
    }
    existing_transport_node_ids = {
        row[0] for row in bind.execute(sa.select(transport_links.c.node_id)).fetchall()
    }

    for row in rows:
        site_id = row.id
        if site_id not in existing_site_ids:
            bind.execute(
                sites.insert().values(id=site_id, name=row.name, description=None)
            )
            existing_site_ids.add(site_id)
        bind.execute(nodes.update().where(nodes.c.id == row.id).values(site_id=site_id))
        if row.site_subnet and (site_id, row.site_subnet) not in existing_prefix_keys:
            bind.execute(
                site_prefixes.insert().values(
                    id=str(uuid.uuid4()),
                    site_id=site_id,
                    prefix=row.site_subnet,
                    advertise=True,
                    priority=100,
                )
            )
            existing_prefix_keys.add((site_id, row.site_subnet))
        if row.id not in existing_transport_node_ids:
            bind.execute(
                transport_links.insert().values(
                    id=str(uuid.uuid4()),
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
            existing_transport_node_ids.add(row.id)


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    if is_sqlite:
        if "_alembic_tmp_nodes" in _table_names():
            op.execute("DROP TABLE _alembic_tmp_nodes")
        if "ix_nodes_site_id" in _index_names("nodes"):
            op.drop_index("ix_nodes_site_id", table_name="nodes")
        if "site_id" in _column_names("nodes"):
            with op.batch_alter_table("nodes") as batch_op:
                batch_op.drop_column("site_id")
    else:
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
