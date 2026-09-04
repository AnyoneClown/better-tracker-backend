"""redesign training workspace

Revision ID: 4d6f8a0b2c4e
Revises: 3c5e7a9b1d4f
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4d6f8a0b2c4e"
down_revision: str | None = "3c5e7a9b1d4f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workouts", sa.Column("completed_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "workouts", sa.Column("rest_timer_ends_at", sa.DateTime(timezone=True))
    )
    op.execute("UPDATE workouts SET completed_at = updated_at")
    op.create_index(
        "uq_workouts_one_active_per_user",
        "workouts",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("completed_at IS NULL"),
    )

    op.add_column(
        "workout_sets",
        sa.Column(
            "is_completed",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )
    op.add_column("workout_sets", sa.Column("position", sa.Integer()))
    op.add_column("workout_sets", sa.Column("rest_seconds", sa.Integer()))
    op.execute(
        """
        WITH ranked AS (
            SELECT id, ROW_NUMBER() OVER (
                PARTITION BY workout_id ORDER BY exercise, set_number, id
            ) AS position
            FROM workout_sets
        )
        UPDATE workout_sets
        SET position = ranked.position
        FROM ranked
        WHERE workout_sets.id = ranked.id
        """
    )
    op.alter_column("workout_sets", "position", nullable=False)
    op.drop_constraint(
        op.f("ck_workout_sets_metric_present"), "workout_sets", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_workout_sets_metric_present"),
        "workout_sets",
        "NOT is_completed OR reps IS NOT NULL OR weight_kg IS NOT NULL "
        "OR distance_km IS NOT NULL OR duration_seconds IS NOT NULL",
    )
    op.create_check_constraint(
        op.f("ck_workout_sets_position_positive"),
        "workout_sets",
        "position > 0",
    )
    op.create_check_constraint(
        op.f("ck_workout_sets_rest_seconds_nonnegative"),
        "workout_sets",
        "rest_seconds IS NULL OR rest_seconds >= 0",
    )
    op.create_unique_constraint(
        "uq_workout_sets_workout_position",
        "workout_sets",
        ["workout_id", "position"],
    )

    op.create_table(
        "workout_routines",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("user_id", sa.Uuid()),
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
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_workout_routines_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workout_routines")),
    )
    op.create_index(
        op.f("ix_workout_routines_user_id"),
        "workout_routines",
        ["user_id"],
    )
    op.create_table(
        "workout_routine_exercises",
        sa.Column("routine_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("exercise", sa.String(length=200), nullable=False),
        sa.Column("set_count", sa.Integer(), nullable=False),
        sa.Column("target_reps", sa.Integer(), nullable=False),
        sa.Column("target_weight_kg", sa.Numeric(10, 3)),
        sa.Column("rest_seconds", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text()),
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
            "position > 0",
            name=op.f("ck_workout_routine_exercises_position_positive"),
        ),
        sa.CheckConstraint(
            "set_count > 0",
            name=op.f("ck_workout_routine_exercises_set_count_positive"),
        ),
        sa.CheckConstraint(
            "target_reps > 0",
            name=op.f("ck_workout_routine_exercises_target_reps_positive"),
        ),
        sa.CheckConstraint(
            "target_weight_kg IS NULL OR target_weight_kg >= 0",
            name=op.f(
                "ck_workout_routine_exercises_target_weight_kg_nonnegative"
            ),
        ),
        sa.CheckConstraint(
            "rest_seconds >= 0",
            name=op.f("ck_workout_routine_exercises_rest_seconds_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["routine_id"],
            ["workout_routines.id"],
            name=op.f(
                "fk_workout_routine_exercises_routine_id_workout_routines"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_workout_routine_exercises")
        ),
        sa.UniqueConstraint(
            "routine_id",
            "exercise",
            name="uq_workout_routine_exercises_routine_exercise",
        ),
        sa.UniqueConstraint(
            "routine_id",
            "position",
            name="uq_workout_routine_exercises_routine_position",
        ),
    )


def downgrade() -> None:
    op.drop_table("workout_routine_exercises")
    op.drop_index(
        op.f("ix_workout_routines_user_id"), table_name="workout_routines"
    )
    op.drop_table("workout_routines")

    op.drop_constraint(
        "uq_workout_sets_workout_position", "workout_sets", type_="unique"
    )
    op.drop_constraint(
        op.f("ck_workout_sets_rest_seconds_nonnegative"),
        "workout_sets",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_workout_sets_position_positive"),
        "workout_sets",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_workout_sets_metric_present"), "workout_sets", type_="check"
    )
    op.execute(
        "DELETE FROM workout_sets WHERE reps IS NULL AND weight_kg IS NULL "
        "AND distance_km IS NULL AND duration_seconds IS NULL"
    )
    op.create_check_constraint(
        op.f("ck_workout_sets_metric_present"),
        "workout_sets",
        "reps IS NOT NULL OR weight_kg IS NOT NULL OR distance_km IS NOT NULL "
        "OR duration_seconds IS NOT NULL",
    )
    op.drop_column("workout_sets", "rest_seconds")
    op.drop_column("workout_sets", "position")
    op.drop_column("workout_sets", "is_completed")

    op.drop_index("uq_workouts_one_active_per_user", table_name="workouts")
    op.drop_column("workouts", "rest_timer_ends_at")
    op.drop_column("workouts", "completed_at")
