"""Hash pre-auth tokens: add token_hash + token_prefix and backfill safely.

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-17
"""
import hashlib

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _column_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    columns = _column_names("preauth_tokens")
    if "token_hash" not in columns:
        op.add_column("preauth_tokens", sa.Column("token_hash", sa.String(), nullable=True))
    if "token_prefix" not in columns:
        op.add_column("preauth_tokens", sa.Column("token_prefix", sa.String(), nullable=True))

    conn = op.get_bind()
    if "token" in _column_names("preauth_tokens"):
        rows = conn.execute(
            sa.text(
                """
                SELECT id, token
                FROM preauth_tokens
                WHERE token_hash IS NULL OR token_prefix IS NULL
                """
            )
        ).fetchall()
        for row in rows:
            token_hash = hashlib.sha256(row.token.encode()).hexdigest()
            token_prefix = row.token[:8]
            conn.execute(
                sa.text(
                    """
                    UPDATE preauth_tokens
                    SET token_hash = :h, token_prefix = :p
                    WHERE id = :id
                    """
                ),
                {"h": token_hash, "p": token_prefix, "id": row.id},
            )

    if "ix_preauth_tokens_token_hash" not in _index_names("preauth_tokens"):
        op.create_index(
            "ix_preauth_tokens_token_hash",
            "preauth_tokens",
            ["token_hash"],
            unique=True,
        )


def downgrade() -> None:
    columns = _column_names("preauth_tokens")
    indexes = _index_names("preauth_tokens")
    if "ix_preauth_tokens_token_hash" in indexes:
        op.drop_index("ix_preauth_tokens_token_hash", table_name="preauth_tokens")
    if "token_hash" in columns:
        op.drop_column("preauth_tokens", "token_hash")
    if "token_prefix" in columns:
        op.drop_column("preauth_tokens", "token_prefix")
