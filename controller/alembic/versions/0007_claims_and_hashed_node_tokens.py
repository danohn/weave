"""add device claims and hashed node auth tokens

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-22 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from argon2 import PasswordHasher

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_hasher = PasswordHasher()


def _column_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    columns = _column_names("nodes")

    op.create_table(
        "device_claims",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("device_id", sa.String(), nullable=False),
        sa.Column("site_name", sa.String(), nullable=True),
        sa.Column("expected_name", sa.String(), nullable=True),
        sa.Column("site_subnet", sa.String(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "UNCLAIMED", "CLAIMED", "ACTIVE", "REVOKED", name="deviceclaimstatus"
            ),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("token_prefix", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_by_node_id", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_device_claims_device_id", "device_claims", ["device_id"], unique=True
    )
    op.create_index(
        "ix_device_claims_token_hash", "device_claims", ["token_hash"], unique=True
    )

    with op.batch_alter_table("nodes") as batch_op:
        if "auth_token_hash" not in columns:
            batch_op.add_column(
                sa.Column("auth_token_hash", sa.String(), nullable=True)
            )
        if "auth_token_prefix" not in columns:
            batch_op.add_column(
                sa.Column("auth_token_prefix", sa.String(), nullable=True)
            )
        if "auth_token_issued_at" not in columns:
            batch_op.add_column(
                sa.Column(
                    "auth_token_issued_at", sa.DateTime(timezone=True), nullable=True
                )
            )
        if "device_claim_id" not in columns:
            batch_op.add_column(
                sa.Column("device_claim_id", sa.String(), nullable=True)
            )
            batch_op.create_foreign_key(
                "fk_nodes_device_claim_id", "device_claims", ["device_claim_id"], ["id"]
            )

    bind = op.get_bind()

    if "auth_token" in columns:
        rows = bind.execute(
            sa.text("SELECT id, auth_token, created_at FROM nodes")
        ).fetchall()
        for row in rows:
            bind.execute(
                sa.text(
                    """
                    UPDATE nodes
                    SET auth_token_hash = :token_hash,
                        auth_token_prefix = :token_prefix,
                        auth_token_issued_at = COALESCE(created_at, CURRENT_TIMESTAMP)
                    WHERE id = :id
                    """
                ),
                {
                    "id": row.id,
                    "token_hash": _hasher.hash(row.auth_token),
                    "token_prefix": row.auth_token[:8],
                },
            )

    preauth_tables = sa.inspect(bind).get_table_names()
    if "preauth_tokens" in preauth_tables:
        rows = bind.execute(
            sa.text(
                """
                SELECT id, token_hash, token_prefix, label, created_at, used_at, used_by_node_id
                FROM preauth_tokens
                """
            )
        ).fetchall()
        for row in rows:
            status = "ACTIVE" if row.used_at else "UNCLAIMED"
            bind.execute(
                sa.text(
                    """
                    INSERT INTO device_claims (
                        id, device_id, token_hash, token_prefix, created_at,
                        claimed_at, claimed_by_node_id, status
                    ) VALUES (
                        :id, :device_id, :token_hash, :token_prefix, :created_at,
                        :claimed_at, :claimed_by_node_id, :status
                    )
                    """
                ),
                {
                    "id": row.id,
                    "device_id": row.label,
                    "token_hash": row.token_hash,
                    "token_prefix": row.token_prefix,
                    "created_at": row.created_at,
                    "claimed_at": row.used_at,
                    "claimed_by_node_id": row.used_by_node_id,
                    "status": status,
                },
            )
            if row.used_by_node_id:
                bind.execute(
                    sa.text(
                        "UPDATE nodes SET device_claim_id = :claim_id WHERE id = :node_id"
                    ),
                    {"claim_id": row.id, "node_id": row.used_by_node_id},
                )

        op.drop_table("preauth_tokens")

    with op.batch_alter_table("nodes") as batch_op:
        batch_op.alter_column(
            "auth_token_hash", existing_type=sa.String(), nullable=False
        )
        batch_op.alter_column(
            "auth_token_prefix", existing_type=sa.String(), nullable=False
        )
        batch_op.alter_column(
            "auth_token_issued_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )
        if "auth_token" in columns:
            indexes = _index_names("nodes")
            if "ix_nodes_auth_token" in indexes:
                batch_op.drop_index("ix_nodes_auth_token")
            batch_op.drop_column("auth_token")

    op.create_index(
        "ix_nodes_auth_token_hash", "nodes", ["auth_token_hash"], unique=False
    )
    op.create_index(
        "ix_nodes_auth_token_prefix", "nodes", ["auth_token_prefix"], unique=False
    )


def downgrade() -> None:
    op.create_table(
        "preauth_tokens",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("token_prefix", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_by_node_id", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_preauth_tokens_token_hash", "preauth_tokens", ["token_hash"], unique=True
    )

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT id, device_id, token_hash, token_prefix, created_at, claimed_at, claimed_by_node_id
            FROM device_claims
            """
        )
    ).fetchall()
    for row in rows:
        bind.execute(
            sa.text(
                """
                INSERT INTO preauth_tokens (
                    id, token_hash, token_prefix, label, created_at, used_at, used_by_node_id
                ) VALUES (
                    :id, :token_hash, :token_prefix, :label, :created_at, :used_at, :used_by_node_id
                )
                """
            ),
            {
                "id": row.id,
                "label": row.device_id,
                "token_hash": row.token_hash,
                "token_prefix": row.token_prefix,
                "created_at": row.created_at,
                "used_at": row.claimed_at,
                "used_by_node_id": row.claimed_by_node_id,
            },
        )

    with op.batch_alter_table("nodes") as batch_op:
        batch_op.add_column(sa.Column("auth_token", sa.String(), nullable=True))
        batch_op.drop_constraint("fk_nodes_device_claim_id", type_="foreignkey")
        batch_op.drop_column("device_claim_id")
        batch_op.drop_column("auth_token_issued_at")
        batch_op.drop_column("auth_token_prefix")
        batch_op.drop_column("auth_token_hash")

    op.drop_index("ix_device_claims_token_hash", table_name="device_claims")
    op.drop_index("ix_device_claims_device_id", table_name="device_claims")
    op.drop_table("device_claims")
