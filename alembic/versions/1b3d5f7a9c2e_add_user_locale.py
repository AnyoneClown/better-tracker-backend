"""add user locale

Revision ID: 1b3d5f7a9c2e
Revises: 0a7b9c1d3e5f
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "1b3d5f7a9c2e"
down_revision: str | None = "0a7b9c1d3e5f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("locale", sa.String(length=2), server_default="uk", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_users_supported_locale"), "users", "locale IN ('en', 'uk')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_users_supported_locale"), "users", type_="check")
    op.drop_column("users", "locale")
