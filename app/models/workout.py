from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UserOwnedMixin, UUIDPrimaryKeyMixin


class Workout(UserOwnedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workouts"
    __table_args__ = (
        CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes > 0",
            name="duration_minutes_positive",
        ),
        Index("ix_workouts_performed_at_id", "performed_at", "id"),
        Index(
            "uq_workouts_one_active_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("completed_at IS NULL"),
            sqlite_where=text("completed_at IS NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    performed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rest_timer_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    sets: Mapped[list[WorkoutSet]] = relationship(
        back_populates="workout",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        order_by=lambda: WorkoutSet.position,
    )

    def replace_sets(self, workout_sets: Iterable[WorkoutSet]) -> None:
        self.sets = list(workout_sets)


class WorkoutSet(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workout_sets"
    __table_args__ = (
        CheckConstraint("set_number > 0", name="set_number_positive"),
        CheckConstraint("position > 0", name="position_positive"),
        CheckConstraint("reps IS NULL OR reps >= 0", name="reps_nonnegative"),
        CheckConstraint(
            "weight_kg IS NULL OR weight_kg >= 0",
            name="weight_kg_nonnegative",
        ),
        CheckConstraint(
            "distance_km IS NULL OR distance_km >= 0",
            name="distance_km_nonnegative",
        ),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name="duration_seconds_nonnegative",
        ),
        CheckConstraint(
            "NOT is_completed OR reps IS NOT NULL OR weight_kg IS NOT NULL "
            "OR distance_km IS NOT NULL OR duration_seconds IS NOT NULL",
            name="metric_present",
        ),
        CheckConstraint(
            "rest_seconds IS NULL OR rest_seconds >= 0",
            name="rest_seconds_nonnegative",
        ),
        UniqueConstraint(
            "workout_id",
            "exercise",
            "set_number",
            name="uq_workout_sets_workout_exercise_number",
        ),
        UniqueConstraint(
            "workout_id",
            "position",
            name="uq_workout_sets_workout_position",
        ),
    )

    workout_id: Mapped[UUID] = mapped_column(
        ForeignKey("workouts.id", ondelete="CASCADE"), nullable=False
    )
    exercise: Mapped[str] = mapped_column(String(200), nullable=False)
    set_number: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_completed: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    rest_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    distance_km: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    workout: Mapped[Workout] = relationship(back_populates="sets")


class WorkoutRoutine(UserOwnedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workout_routines"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    exercises: Mapped[list[WorkoutRoutineExercise]] = relationship(
        back_populates="routine",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        order_by=lambda: WorkoutRoutineExercise.position,
    )

    def replace_exercises(
        self, exercises: Iterable[WorkoutRoutineExercise]
    ) -> None:
        self.exercises = list(exercises)


class WorkoutRoutineExercise(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workout_routine_exercises"
    __table_args__ = (
        CheckConstraint("position > 0", name="position_positive"),
        CheckConstraint("set_count > 0", name="set_count_positive"),
        CheckConstraint("target_reps > 0", name="target_reps_positive"),
        CheckConstraint(
            "target_weight_kg IS NULL OR target_weight_kg >= 0",
            name="target_weight_kg_nonnegative",
        ),
        CheckConstraint("rest_seconds >= 0", name="rest_seconds_nonnegative"),
        UniqueConstraint(
            "routine_id",
            "position",
            name="uq_workout_routine_exercises_routine_position",
        ),
        UniqueConstraint(
            "routine_id",
            "exercise",
            name="uq_workout_routine_exercises_routine_exercise",
        ),
    )

    routine_id: Mapped[UUID] = mapped_column(
        ForeignKey("workout_routines.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    exercise: Mapped[str] = mapped_column(String(200), nullable=False)
    set_count: Mapped[int] = mapped_column(Integer, nullable=False)
    target_reps: Mapped[int] = mapped_column(Integer, nullable=False)
    target_weight_kg: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 3), nullable=True
    )
    rest_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    routine: Mapped[WorkoutRoutine] = relationship(back_populates="exercises")
