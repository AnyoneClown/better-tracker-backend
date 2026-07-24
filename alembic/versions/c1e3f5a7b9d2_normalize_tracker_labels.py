"""normalize tracker labels

Revision ID: c1e3f5a7b9d2
Revises: 9c2d4e6f8a10
Create Date: 2026-07-24 23:00:00.000000
"""

from collections.abc import Callable, Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "c1e3f5a7b9d2"
down_revision: str | Sequence[str] | None = "9c2d4e6f8a10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _normalize(value: str) -> str:
    return " ".join(value.split()).casefold()


def _normalized_rows(
    table: sa.TableClause,
    value_column: sa.ColumnClause[Any],
    max_length: int,
) -> list[tuple[Any, str]]:
    connection = op.get_bind()
    rows = connection.execute(sa.select(table.c.id, value_column)).all()
    normalized_rows = [(row.id, _normalize(row[1])) for row in rows]
    if any(not value for _, value in normalized_rows):
        raise RuntimeError(f"{table.name} contains a label that normalizes to empty")
    if any(len(value) > max_length for _, value in normalized_rows):
        raise RuntimeError(
            f"{table.name} contains a normalized label longer than {max_length}"
        )
    return normalized_rows


def _reject_collisions(
    rows: Sequence[Any],
    key: Callable[[Any], tuple[Any, ...]],
    label: str,
) -> None:
    seen: set[tuple[Any, ...]] = set()
    for row in rows:
        identity = key(row)
        if identity in seen:
            raise RuntimeError(
                f"cannot normalize {label}: existing rows would violate uniqueness"
            )
        seen.add(identity)


def upgrade() -> None:
    """Canonicalize labels written before API-level normalization existed."""
    connection = op.get_bind()
    transactions = sa.table(
        "financial_transactions",
        sa.column("id", sa.Uuid()),
        sa.column("category", sa.String()),
    )
    budgets = sa.table(
        "monthly_budgets",
        sa.column("id", sa.Uuid()),
        sa.column("year", sa.Integer()),
        sa.column("month", sa.Integer()),
        sa.column("category", sa.String()),
        sa.column("currency", sa.String()),
    )
    workout_sets = sa.table(
        "workout_sets",
        sa.column("id", sa.Uuid()),
        sa.column("workout_id", sa.Uuid()),
        sa.column("exercise", sa.String()),
        sa.column("set_number", sa.Integer()),
    )

    budget_rows = connection.execute(sa.select(budgets)).all()
    _reject_collisions(
        budget_rows,
        lambda row: (
            row.year,
            row.month,
            _normalize(row.category),
            row.currency,
        ),
        "monthly budget categories",
    )
    set_rows = connection.execute(sa.select(workout_sets)).all()
    _reject_collisions(
        set_rows,
        lambda row: (row.workout_id, _normalize(row.exercise), row.set_number),
        "workout exercises",
    )

    for table, column, max_length in (
        (transactions, transactions.c.category, 100),
        (budgets, budgets.c.category, 100),
        (workout_sets, workout_sets.c.exercise, 200),
    ):
        for row_id, normalized in _normalized_rows(table, column, max_length):
            connection.execute(
                table.update()
                .where(table.c.id == row_id)
                .values({column.name: normalized})
            )


def downgrade() -> None:
    """Normalization is intentionally irreversible; schema is unchanged."""
