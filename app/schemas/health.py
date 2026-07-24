from datetime import date
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import EntityResponse


class WeightEntryCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    recorded_on: date
    weight_kg: Decimal = Field(gt=0, max_digits=6, decimal_places=2)
    body_fat_percent: Decimal | None = Field(
        default=None,
        ge=0,
        le=100,
        max_digits=5,
        decimal_places=2,
    )
    notes: str | None = Field(default=None, max_length=500)


class WeightEntryUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    recorded_on: date | None = None
    weight_kg: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=6,
        decimal_places=2,
    )
    body_fat_percent: Decimal | None = Field(
        default=None,
        ge=0,
        le=100,
        max_digits=5,
        decimal_places=2,
    )
    notes: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        null_fields = {
            field
            for field in {"recorded_on", "weight_kg"} & self.model_fields_set
            if getattr(self, field) is None
        }
        if null_fields:
            fields = ", ".join(sorted(null_fields))
            raise ValueError(f"fields cannot be null: {fields}")
        return self


class WeightEntryResponse(EntityResponse):
    recorded_on: date
    weight_kg: Decimal
    body_fat_percent: Decimal | None
    notes: str | None


class WeightEntryListResponse(BaseModel):
    items: list[WeightEntryResponse]
    total: int
    offset: int
    limit: int


class NutritionLogCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    recorded_on: date
    calories: int = Field(ge=0)
    calorie_target: int | None = Field(default=None, gt=0)
    protein_grams: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=8,
        decimal_places=2,
    )
    carbs_grams: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=8,
        decimal_places=2,
    )
    fat_grams: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=8,
        decimal_places=2,
    )
    notes: str | None = Field(default=None, max_length=500)


class NutritionLogUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    recorded_on: date | None = None
    calories: int | None = Field(default=None, ge=0)
    calorie_target: int | None = Field(default=None, gt=0)
    protein_grams: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=8,
        decimal_places=2,
    )
    carbs_grams: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=8,
        decimal_places=2,
    )
    fat_grams: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=8,
        decimal_places=2,
    )
    notes: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        null_fields = {
            field
            for field in {"recorded_on", "calories"} & self.model_fields_set
            if getattr(self, field) is None
        }
        if null_fields:
            fields = ", ".join(sorted(null_fields))
            raise ValueError(f"fields cannot be null: {fields}")
        return self


class NutritionLogResponse(EntityResponse):
    recorded_on: date
    calories: int
    calorie_target: int | None
    protein_grams: Decimal | None
    carbs_grams: Decimal | None
    fat_grams: Decimal | None
    notes: str | None


class NutritionLogListResponse(BaseModel):
    items: list[NutritionLogResponse]
    total: int
    offset: int
    limit: int


class HealthSummary(BaseModel):
    start_date: date | None
    end_date: date | None
    latest_weight_kg: Decimal | None
    weight_change_kg: Decimal | None
    nutrition_days_logged: int
    total_calories: int
    average_daily_calories: Decimal | None
    average_calorie_target: Decimal | None
