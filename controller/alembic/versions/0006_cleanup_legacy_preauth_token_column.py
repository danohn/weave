"""Remove legacy plaintext pre-auth token storage.

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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
    indexes = _index_names("preauth_tokens")

    with op.batch_alter_table("preauth_tokens") as batch_op:
        if "token_hash" in columns:
            batch_op.alter_column(
                "token_hash", existing_type=sa.String(), nullable=False
            )
        if "token_prefix" in columns:
            batch_op.alter_column(
                "token_prefix", existing_type=sa.String(), nullable=False
            )
        if "ix_preauth_tokens_token" in indexes:
            batch_op.drop_index("ix_preauth_tokens_token")
        if "token" in columns:
            batch_op.drop_column("token")


def downgrade() -> None:
    columns = _column_names("preauth_tokens")

    with op.batch_alter_table("preauth_tokens") as batch_op:
        if "token" not in columns:
            batch_op.add_column(sa.Column("token", sa.String(), nullable=True))
        if "token_hash" in columns:
            batch_op.alter_column(
                "token_hash", existing_type=sa.String(), nullable=True
            )
        if "token_prefix" in columns:
            batch_op.alter_column(
                "token_prefix", existing_type=sa.String(), nullable=True
            )

    indexes = _index_names("preauth_tokens")
    if "ix_preauth_tokens_token" not in indexes:
        op.create_index(
            "ix_preauth_tokens_token", "preauth_tokens", ["token"], unique=True
        )
