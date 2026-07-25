from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SQLAlchemyEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UserOwnedMixin, UUIDPrimaryKeyMixin


class TransactionKind(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"


class TransactionSource(StrEnum):
    MANUAL = "manual"
    MONOBANK = "monobank"
    PRIVATBANK = "privatbank"


class FinancialTransaction(
    UserOwnedMixin,
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "financial_transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("length(currency) = 3", name="currency_three_chars"),
        Index(
            "ix_financial_transactions_currency_occurred_on",
            "currency",
            "occurred_on",
        ),
        UniqueConstraint(
            "user_id",
            "source",
            "external_account_id",
            "external_transaction_id",
            name="uq_financial_transactions_external_source",
        ),
    )

    kind: Mapped[TransactionKind] = mapped_column(
        SQLAlchemyEnum(
            TransactionKind,
            name="financial_transaction_kind",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
        index=True,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="USD",
        server_default="USD",
    )
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[TransactionSource] = mapped_column(
        SQLAlchemyEnum(
            TransactionSource,
            name="financial_transaction_source",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
        default=TransactionSource.MANUAL,
        server_default=TransactionSource.MANUAL.value,
        index=True,
    )
    external_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_transaction_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    occurred_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    mcc: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hold: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    mapped_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    category_override: Mapped[str | None] = mapped_column(String(100), nullable=True)
    excluded_from_summary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    provider_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "cockroachdb"), nullable=True
    )


class MonthlyBudget(UserOwnedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "monthly_budgets"
    __table_args__ = (
        CheckConstraint("year >= 1 AND year <= 9999", name="year_valid"),
        CheckConstraint("month >= 1 AND month <= 12", name="month_valid"),
        CheckConstraint("limit_amount > 0", name="limit_amount_positive"),
        CheckConstraint("length(currency) = 3", name="currency_three_chars"),
        UniqueConstraint(
            "user_id",
            "year",
            "month",
            "category",
            "currency",
            name="uq_monthly_budgets_period_category_currency",
        ),
        Index("ix_monthly_budgets_period_currency", "year", "month", "currency"),
    )

    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="USD",
        server_default="USD",
    )
    limit_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
