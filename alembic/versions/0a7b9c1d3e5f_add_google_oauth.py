"""add google oauth

Revision ID: 0a7b9c1d3e5f
Revises: f4a6b8c0d2e3
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0a7b9c1d3e5f"
down_revision: str | None = "f4a6b8c0d2e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("google_subject", sa.String(length=255), nullable=True),
    )
    op.create_unique_constraint(
        "uq_users_google_subject",
        "users",
        ["google_subject"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_users_google_subject", "users", type_="unique")
    op.drop_column("users", "google_subject")
