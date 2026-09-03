"""remove privatbank integration

Revision ID: f4a6b8c0d2e3
Revises: e3f5a7b9c1d4
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f4a6b8c0d2e3"
down_revision: str | None = "e3f5a7b9c1d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("privatbank_accounts")
    op.drop_table("privatbank_connections")
    op.execute(
        sa.text("DELETE FROM financial_transactions WHERE source = 'privatbank'")
    )
    op.drop_constraint(
        "financial_transaction_source",
        "financial_transactions",
        type_="check",
    )
    op.alter_column(
        "financial_transactions",
        "source",
        existing_type=sa.String(length=10),
        type_=sa.String(length=8),
        existing_nullable=False,
        existing_server_default="manual",
    )
    op.create_check_constraint(
        "financial_transaction_source",
        "financial_transactions",
        "source IN ('manual', 'monobank')",
    )


def downgrade() -> None:
    raise RuntimeError("PrivatBank removal deletes credentials and imported data")
