"""track monobank jars and ignore new sources by default

Revision ID: 3c5e7a9b1d4f
Revises: 1b3d5f7a9c2e
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "3c5e7a9b1d4f"
down_revision: str | None = "1b3d5f7a9c2e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "monobank_jars",
        sa.Column(
            "is_tracked",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )
    op.alter_column(
        "monobank_jars",
        "is_tracked",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.false(),
    )
    op.alter_column(
        "monobank_accounts",
        "is_tracked",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.false(),
    )


def downgrade() -> None:
    op.alter_column(
        "monobank_accounts",
        "is_tracked",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.true(),
    )
    op.drop_column("monobank_jars", "is_tracked")
