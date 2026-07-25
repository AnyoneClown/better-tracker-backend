"""add authentication ownership

Revision ID: f8b5c3d1e2a4
Revises: e7a4b2c9d1f0
Create Date: 2026-07-25 22:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f8b5c3d1e2a4"
down_revision: str | Sequence[str] | None = "e7a4b2c9d1f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OWNED_TABLES = (
    "financial_accounts",
    "financial_transactions",
    "monthly_budgets",
    "net_worth_snapshots",
    "nutrition_logs",
    "savings_goals",
    "weight_entries",
    "workouts",
)

SCOPED_UNIQUE_CONSTRAINTS = (
    (
        "financial_accounts",
        "uq_account_name_currency",
        ("user_id", "name", "currency"),
        ("name", "currency"),
    ),
    (
        "monthly_budgets",
        "uq_monthly_budgets_period_category_currency",
        ("user_id", "year", "month", "category", "currency"),
        ("year", "month", "category", "currency"),
    ),
    (
        "nutrition_logs",
        "uq_nutrition_log_recorded_on",
        ("user_id", "recorded_on"),
        ("recorded_on",),
    ),
    (
        "savings_goals",
        "uq_savings_goal_name_currency",
        ("user_id", "name", "currency"),
        ("name", "currency"),
    ),
    (
        "weight_entries",
        "uq_weight_entry_recorded_on",
        ("user_id", "recorded_on"),
        ("recorded_on",),
    ),
)


def upgrade() -> None:
    """Add access-token account state and per-user tracker ownership."""
    op.add_column(
        "users",
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )

    for table_name in OWNED_TABLES:
        op.add_column(
            table_name,
            sa.Column("user_id", sa.Uuid(), nullable=True),
        )
        op.create_foreign_key(
            op.f(f"fk_{table_name}_user_id_users"),
            table_name,
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_index(
            op.f(f"ix_{table_name}_user_id"),
            table_name,
            ["user_id"],
            unique=False,
        )

    for table_name, constraint_name, scoped_columns, _ in SCOPED_UNIQUE_CONSTRAINTS:
        op.drop_constraint(constraint_name, table_name, type_="unique")
        op.create_unique_constraint(
            constraint_name,
            table_name,
            list(scoped_columns),
        )


def downgrade() -> None:
    """Remove user ownership and restore single-user uniqueness."""
    for table_name, constraint_name, _, legacy_columns in reversed(
        SCOPED_UNIQUE_CONSTRAINTS
    ):
        op.drop_constraint(constraint_name, table_name, type_="unique")
        op.create_unique_constraint(
            constraint_name,
            table_name,
            list(legacy_columns),
        )

    for table_name in reversed(OWNED_TABLES):
        op.drop_index(op.f(f"ix_{table_name}_user_id"), table_name=table_name)
        op.drop_constraint(
            op.f(f"fk_{table_name}_user_id_users"),
            table_name,
            type_="foreignkey",
        )
        op.drop_column(table_name, "user_id")

    op.drop_column("users", "is_active")
