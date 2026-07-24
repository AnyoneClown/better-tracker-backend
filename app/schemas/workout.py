from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import EntityResponse


class WorkoutSetBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    exercise: str = Field(min_length=1, max_length=200)
    set_number: int = Field(ge=1)
    reps: int | None = Field(default=None, ge=0)
    weight_kg: Decimal | None = Field(
        default=None, ge=0, max_digits=10, decimal_places=3
    )
    distance_km: Decimal | None = Field(
        default=None, ge=0, max_digits=12, decimal_places=3
    )
    duration_seconds: int | None = Field(default=None, ge=0)
    notes: str | None = None

    @field_validator("exercise", mode="before")
    @classmethod
    def normalize_exercise(cls, value: str) -> str:
        return " ".join(value.split()).casefold()

    @model_validator(mode="after")
    def require_metric(self) -> WorkoutSetBase:
        metrics = (
            self.reps,
            self.weight_kg,
            self.distance_km,
            self.duration_seconds,
        )
        if all(metric is None for metric in metrics):
            raise ValueError("a workout set must contain at least one metric")
        return self


class WorkoutSetCreate(WorkoutSetBase):
    pass


class WorkoutSetRead(WorkoutSetBase, EntityResponse):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    workout_id: UUID


class WorkoutBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    performed_at: datetime
    duration_minutes: int | None = Field(default=None, gt=0)
    notes: str | None = None

    @field_validator("performed_at")
    @classmethod
    def performed_at_must_have_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("performed_at must include a timezone offset")
        return value


class WorkoutCreate(WorkoutBase):
    sets: list[WorkoutSetCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def set_numbers_must_be_unique_per_exercise(self) -> WorkoutCreate:
        _validate_unique_sets(self.sets)
        return self


class WorkoutUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    performed_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, gt=0)
    notes: str | None = None
    sets: list[WorkoutSetCreate] = Field(default_factory=list)

    @field_validator("performed_at")
    @classmethod
    def performed_at_must_have_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("performed_at must include a timezone offset")
        return value

    @model_validator(mode="after")
    def validate_update(self) -> WorkoutUpdate:
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        for field_name in ("name", "performed_at"):
            if (
                field_name in self.model_fields_set
                and getattr(self, field_name) is None
            ):
                raise ValueError(f"{field_name} cannot be null")
        if "sets" in self.model_fields_set:
            _validate_unique_sets(self.sets)
        return self


class WorkoutRead(WorkoutBase, EntityResponse):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    sets: list[WorkoutSetRead]


class WorkoutListResponse(BaseModel):
    items: list[WorkoutRead]
    total: int
    offset: int
    limit: int


class WorkoutExerciseSummary(BaseModel):
    exercise: str
    sets: int
    total_reps: int
    volume_kg: Decimal
    distance_km: Decimal
    duration_seconds: int


class WorkoutSummary(BaseModel):
    date_from: datetime | None
    date_to: datetime | None
    workout_count: int
    total_duration_minutes: int
    average_duration_minutes: Decimal | None
    total_sets: int
    total_reps: int
    total_volume_kg: Decimal
    total_distance_km: Decimal
    total_set_duration_seconds: int
    exercises: list[WorkoutExerciseSummary]


def _validate_unique_sets(workout_sets: list[WorkoutSetCreate]) -> None:
    seen: set[tuple[str, int]] = set()
    for workout_set in workout_sets:
        identity = (workout_set.exercise.casefold(), workout_set.set_number)
        if identity in seen:
            raise ValueError("set_number must be unique within each exercise")
        seen.add(identity)
