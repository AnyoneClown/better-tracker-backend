from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Workout(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workouts"
    __table_args__ = (
        CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes > 0",
            name="duration_minutes_positive",
        ),
        Index("ix_workouts_performed_at_id", "performed_at", "id"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    performed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    sets: Mapped[list[WorkoutSet]] = relationship(
        back_populates="workout",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        order_by=lambda: (WorkoutSet.exercise, WorkoutSet.set_number),
    )

    def replace_sets(self, workout_sets: Iterable[WorkoutSet]) -> None:
        self.sets = list(workout_sets)


class WorkoutSet(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workout_sets"
    __table_args__ = (
        CheckConstraint("set_number > 0", name="set_number_positive"),
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
            "reps IS NOT NULL OR weight_kg IS NOT NULL "
            "OR distance_km IS NOT NULL OR duration_seconds IS NOT NULL",
            name="metric_present",
        ),
        UniqueConstraint(
            "workout_id",
            "exercise",
            "set_number",
            name="uq_workout_sets_workout_exercise_number",
        ),
    )

    workout_id: Mapped[UUID] = mapped_column(
        ForeignKey("workouts.id", ondelete="CASCADE"), nullable=False
    )
    exercise: Mapped[str] = mapped_column(String(200), nullable=False)
    set_number: Mapped[int] = mapped_column(Integer, nullable=False)
    reps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    distance_km: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    workout: Mapped[Workout] = relationship(back_populates="sets")
