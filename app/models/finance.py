from datetime import date
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Date,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SQLAlchemyEnum,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TransactionKind(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"


class FinancialTransaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "financial_transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("length(currency) = 3", name="currency_three_chars"),
        Index(
            "ix_financial_transactions_currency_occurred_on",
            "currency",
            "occurred_on",
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


class MonthlyBudget(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "monthly_budgets"
    __table_args__ = (
        CheckConstraint("year >= 1 AND year <= 9999", name="year_valid"),
        CheckConstraint("month >= 1 AND month <= 12", name="month_valid"),
        CheckConstraint("limit_amount > 0", name="limit_amount_positive"),
        CheckConstraint("length(currency) = 3", name="currency_three_chars"),
        UniqueConstraint(
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
