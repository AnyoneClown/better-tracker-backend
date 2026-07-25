"""add users

Revision ID: e7a4b2c9d1f0
Revises: c1e3f5a7b9d2
Create Date: 2026-07-25 01:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e7a4b2c9d1f0"
down_revision: str | Sequence[str] | None = "c1e3f5a7b9d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create registered user accounts."""
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(email) <= 254",
            name=op.f("ck_users_email_max_length"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )


def downgrade() -> None:
    """Remove registered user accounts."""
    op.drop_table("users")
