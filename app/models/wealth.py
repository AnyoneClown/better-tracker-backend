from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AccountType(StrEnum):
    ASSET = "asset"
    LIABILITY = "liability"


class FinancialAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "financial_accounts"
    __table_args__ = (
        CheckConstraint("balance >= 0", name="balance_nonnegative"),
        CheckConstraint("length(currency) = 3", name="currency_three_chars"),
        CheckConstraint(
            "NOT is_savings OR account_type = 'asset'",
            name="savings_account_is_asset",
        ),
        UniqueConstraint("name", "currency", name="uq_account_name_currency"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    account_type: Mapped[AccountType] = mapped_column(
        Enum(
            AccountType,
            name="account_type",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    include_in_net_worth: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    is_savings: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )


class SavingsGoal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "savings_goals"
    __table_args__ = (
        CheckConstraint("target_amount > 0", name="target_amount_positive"),
        CheckConstraint("current_amount >= 0", name="current_amount_nonnegative"),
        CheckConstraint("length(currency) = 3", name="currency_three_chars"),
        UniqueConstraint("name", "currency", name="uq_savings_goal_name_currency"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    target_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    current_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    @property
    def progress_percent(self) -> Decimal:
        return (self.current_amount / self.target_amount * 100).quantize(
            Decimal("0.01")
        )


class NetWorthSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "net_worth_snapshots"
    __table_args__ = (
        CheckConstraint("assets >= 0", name="assets_nonnegative"),
        CheckConstraint("liabilities >= 0", name="liabilities_nonnegative"),
        CheckConstraint("length(currency) = 3", name="currency_three_chars"),
    )

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    assets: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    liabilities: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    @property
    def net_worth(self) -> Decimal:
        return self.assets - self.liabilities
