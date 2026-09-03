"""add monobank account tracking

Revision ID: e3f5a7b9c1d4
Revises: d2f4a6b8c0e1
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e3f5a7b9c1d4"
down_revision: str | None = "d2f4a6b8c0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "monobank_accounts",
        sa.Column(
            "is_tracked",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("monobank_accounts", "is_tracked")
