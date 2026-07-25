from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UserOwnedMixin, UUIDPrimaryKeyMixin


class WeightEntry(UserOwnedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "weight_entries"
    __table_args__ = (
        CheckConstraint("weight_kg > 0", name="weight_kg_positive"),
        CheckConstraint(
            "body_fat_percent IS NULL OR "
            "(body_fat_percent >= 0 AND body_fat_percent <= 100)",
            name="body_fat_percent_range",
        ),
        UniqueConstraint(
            "user_id",
            "recorded_on",
            name="uq_weight_entry_recorded_on",
        ),
    )

    recorded_on: Mapped[date] = mapped_column(Date, nullable=False)
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    body_fat_percent: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)


class NutritionLog(UserOwnedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "nutrition_logs"
    __table_args__ = (
        CheckConstraint("calories >= 0", name="calories_nonnegative"),
        CheckConstraint(
            "calorie_target IS NULL OR calorie_target > 0",
            name="calorie_target_positive",
        ),
        CheckConstraint(
            "protein_grams IS NULL OR protein_grams >= 0",
            name="protein_grams_nonnegative",
        ),
        CheckConstraint(
            "carbs_grams IS NULL OR carbs_grams >= 0",
            name="carbs_grams_nonnegative",
        ),
        CheckConstraint(
            "fat_grams IS NULL OR fat_grams >= 0",
            name="fat_grams_nonnegative",
        ),
        UniqueConstraint(
            "user_id",
            "recorded_on",
            name="uq_nutrition_log_recorded_on",
        ),
    )

    recorded_on: Mapped[date] = mapped_column(Date, nullable=False)
    calories: Mapped[int] = mapped_column(Integer, nullable=False)
    calorie_target: Mapped[int | None] = mapped_column(Integer, nullable=True)
    protein_grams: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    carbs_grams: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    fat_grams: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
