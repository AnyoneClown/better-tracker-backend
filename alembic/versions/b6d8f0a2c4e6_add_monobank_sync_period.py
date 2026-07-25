"""add monobank sync period

Revision ID: b6d8f0a2c4e6
Revises: a4c6e8f0b2d4
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b6d8f0a2c4e6"
down_revision: str | None = "a4c6e8f0b2d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "monobank_connections",
        sa.Column("sync_date_from", sa.Date(), nullable=True),
    )
    op.add_column(
        "monobank_connections",
        sa.Column("sync_date_to", sa.Date(), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_monobank_connections_sync_date_range_valid"),
        "monobank_connections",
        "sync_date_from IS NULL OR sync_date_to IS NULL "
        "OR sync_date_from <= sync_date_to",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_monobank_connections_sync_date_range_valid"),
        "monobank_connections",
        type_="check",
    )
    op.drop_column("monobank_connections", "sync_date_to")
    op.drop_column("monobank_connections", "sync_date_from")
