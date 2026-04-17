"""Hash pre-auth tokens: replace plaintext token column with token_hash + token_prefix.

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


def upgrade() -> None:
    op.add_column("preauth_tokens", sa.Column("token_hash", sa.String(), nullable=True))
    op.add_column("preauth_tokens", sa.Column("token_prefix", sa.String(), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, token FROM preauth_tokens")).fetchall()
    for row in rows:
        token_hash = hashlib.sha256(row.token.encode()).hexdigest()
        token_prefix = row.token[:8]
        conn.execute(
            sa.text(
                "UPDATE preauth_tokens SET token_hash = :h, token_prefix = :p WHERE id = :id"
            ),
            {"h": token_hash, "p": token_prefix, "id": row.id},
        )

    op.alter_column("preauth_tokens", "token_hash", nullable=False)
    op.alter_column("preauth_tokens", "token_prefix", nullable=False)
    op.create_index(
        "ix_preauth_tokens_token_hash", "preauth_tokens", ["token_hash"], unique=True
    )
    op.drop_index("ix_preauth_tokens_token", table_name="preauth_tokens")
    op.drop_column("preauth_tokens", "token")


def downgrade() -> None:
    op.add_column("preauth_tokens", sa.Column("token", sa.String(), nullable=True))
    op.drop_index("ix_preauth_tokens_token_hash", table_name="preauth_tokens")
    op.drop_column("preauth_tokens", "token_hash")
    op.drop_column("preauth_tokens", "token_prefix")
