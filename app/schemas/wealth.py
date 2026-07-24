from datetime import date, datetime
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.wealth import AccountType
from app.schemas.common import EntityResponse


class CurrencyModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    currency: str = Field(
        default="USD",
        min_length=3,
        max_length=3,
        pattern=r"^[A-Za-z]{3}$",
    )

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class FinancialAccountCreate(CurrencyModel):
    name: str = Field(min_length=1, max_length=120)
    account_type: AccountType
    category: str = Field(min_length=1, max_length=80)
    balance: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    include_in_net_worth: bool = True
    is_savings: bool = False

    @model_validator(mode="after")
    def savings_must_be_asset(self) -> "FinancialAccountCreate":
        if self.is_savings and self.account_type != AccountType.ASSET:
            raise ValueError("a savings account must be an asset")
        return self


class FinancialAccountUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=120)
    account_type: AccountType | None = None
    category: str | None = Field(default=None, min_length=1, max_length=80)
    balance: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=18,
        decimal_places=2,
    )
    currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Za-z]{3}$",
    )
    include_in_net_worth: bool | None = None
    is_savings: bool | None = None

    @field_validator("currency")
    @classmethod
    def normalize_optional_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.upper()

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        required_fields = {
            "name",
            "account_type",
            "category",
            "balance",
            "currency",
            "include_in_net_worth",
            "is_savings",
        }
        null_fields = {
            field
            for field in required_fields & self.model_fields_set
            if getattr(self, field) is None
        }
        if null_fields:
            fields = ", ".join(sorted(null_fields))
            raise ValueError(f"fields cannot be null: {fields}")
        return self


class FinancialAccountResponse(EntityResponse):
    name: str
    account_type: AccountType
    category: str
    balance: Decimal
    currency: str
    include_in_net_worth: bool
    is_savings: bool


class SavingsGoalCreate(CurrencyModel):
    name: str = Field(min_length=1, max_length=120)
    target_amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    current_amount: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        max_digits=18,
        decimal_places=2,
    )
    target_date: date | None = None
    notes: str | None = Field(default=None, max_length=500)


class SavingsGoalUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=120)
    target_amount: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=18,
        decimal_places=2,
    )
    current_amount: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=18,
        decimal_places=2,
    )
    currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Za-z]{3}$",
    )
    target_date: date | None = None
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("currency")
    @classmethod
    def normalize_optional_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.upper()

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        required_fields = {"name", "target_amount", "current_amount", "currency"}
        null_fields = {
            field
            for field in required_fields & self.model_fields_set
            if getattr(self, field) is None
        }
        if null_fields:
            fields = ", ".join(sorted(null_fields))
            raise ValueError(f"fields cannot be null: {fields}")
        return self


class SavingsGoalResponse(EntityResponse):
    name: str
    target_amount: Decimal
    current_amount: Decimal
    currency: str
    target_date: date | None
    notes: str | None
    progress_percent: Decimal


class NetWorthSnapshotCapture(CurrencyModel):
    recorded_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("recorded_at")
    @classmethod
    def recorded_at_must_have_timezone(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("recorded_at must include a timezone offset")
        return value


class NetWorthSnapshotResponse(EntityResponse):
    recorded_at: datetime
    assets: Decimal
    liabilities: Decimal
    net_worth: Decimal
    currency: str
    notes: str | None


class WealthSummary(BaseModel):
    currency: str
    assets: Decimal
    liabilities: Decimal
    net_worth: Decimal
    savings: Decimal
    savings_goal_target: Decimal
    savings_goal_current: Decimal
