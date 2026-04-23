"""add transport overlay addresses and keys

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-23 00:30:00.000000

"""
import ipaddress
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULT_TRANSPORT_SUBNETS = {
    "internet": "10.0.0.0/24",
    "mpls": "10.0.1.0/24",
    "lte": "10.0.2.0/24",
    "other": "10.0.3.0/24",
}


def _column_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def _controller_ip(kind: str) -> str:
    network = ipaddress.ip_network(_DEFAULT_TRANSPORT_SUBNETS[kind], strict=False)
    return str(list(network.hosts())[-1])


def upgrade() -> None:
    columns = _column_names("transport_links")
    indexes = _index_names("transport_links")
    with op.batch_alter_table("transport_links") as batch_op:
        if "wireguard_public_key" not in columns:
            batch_op.add_column(sa.Column("wireguard_public_key", sa.String(), nullable=True))
        if "overlay_vpn_ip" not in columns:
            batch_op.add_column(sa.Column("overlay_vpn_ip", sa.String(), nullable=True))
        if "controller_vpn_ip" not in columns:
            batch_op.add_column(sa.Column("controller_vpn_ip", sa.String(), nullable=True))

    if "ix_transport_links_wireguard_public_key" not in indexes:
        op.create_index(
            "ix_transport_links_wireguard_public_key",
            "transport_links",
            ["wireguard_public_key"],
            unique=True,
        )
    if "ix_transport_links_overlay_vpn_ip" not in indexes:
        op.create_index(
            "ix_transport_links_overlay_vpn_ip",
            "transport_links",
            ["overlay_vpn_ip"],
            unique=True,
        )

    bind = op.get_bind()
    metadata = sa.MetaData()
    transport_links = sa.Table("transport_links", metadata, autoload_with=bind)
    nodes = sa.Table("nodes", metadata, autoload_with=bind)

    rows = bind.execute(
        sa.select(
            transport_links.c.id,
            transport_links.c.node_id,
            transport_links.c.kind,
            transport_links.c.overlay_vpn_ip,
            transport_links.c.controller_vpn_ip,
            transport_links.c.wireguard_public_key,
            nodes.c.vpn_ip,
            nodes.c.wireguard_public_key.label("node_wg_key"),
        ).select_from(transport_links.join(nodes, transport_links.c.node_id == nodes.c.id))
    ).fetchall()

    for row in rows:
        updates: dict[str, str] = {}
        kind = str(row.kind).lower()
        if row.overlay_vpn_ip is None:
            updates["overlay_vpn_ip"] = row.vpn_ip
        if row.controller_vpn_ip is None:
            updates["controller_vpn_ip"] = _controller_ip(kind if kind in _DEFAULT_TRANSPORT_SUBNETS else "other")
        if row.wireguard_public_key is None:
            updates["wireguard_public_key"] = row.node_wg_key
        if updates:
            bind.execute(
                transport_links.update().where(transport_links.c.id == row.id).values(**updates)
            )


def downgrade() -> None:
    if "ix_transport_links_overlay_vpn_ip" in _index_names("transport_links"):
        op.drop_index("ix_transport_links_overlay_vpn_ip", table_name="transport_links")
    if "ix_transport_links_wireguard_public_key" in _index_names("transport_links"):
        op.drop_index("ix_transport_links_wireguard_public_key", table_name="transport_links")

    with op.batch_alter_table("transport_links") as batch_op:
        if "controller_vpn_ip" in _column_names("transport_links"):
            batch_op.drop_column("controller_vpn_ip")
        if "overlay_vpn_ip" in _column_names("transport_links"):
            batch_op.drop_column("overlay_vpn_ip")
        if "wireguard_public_key" in _column_names("transport_links"):
            batch_op.drop_column("wireguard_public_key")
