"""add savings contributions

Revision ID: 9c2d4e6f8a10
Revises: 5b9bcb7a5474
Create Date: 2026-07-24 22:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9c2d4e6f8a10"
down_revision: str | Sequence[str] | None = "5b9bcb7a5474"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the savings movement history."""
    op.create_table(
        "savings_contributions",
        sa.Column("goal_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "contribution",
                "withdrawal",
                name="savings_contribution_kind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("notes", sa.String(length=500), nullable=True),
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
            "amount > 0",
            name=op.f("ck_savings_contributions_amount_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["goal_id"],
            ["savings_goals.id"],
            name=op.f("fk_savings_contributions_goal_id_savings_goals"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_savings_contributions"),
        ),
    )
    op.create_index(
        "ix_savings_contributions_goal_occurred_on",
        "savings_contributions",
        ["goal_id", "occurred_on"],
        unique=False,
    )


def downgrade() -> None:
    """Remove savings movement history."""
    op.drop_index(
        "ix_savings_contributions_goal_occurred_on",
        table_name="savings_contributions",
    )
    op.drop_table("savings_contributions")
