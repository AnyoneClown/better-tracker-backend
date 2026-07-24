from datetime import date, datetime
from decimal import Decimal
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.wealth import AccountType, SavingsContributionKind
from app.schemas.common import EntityResponse


class CurrencyModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

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
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

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


class FinancialAccountListResponse(BaseModel):
    items: list[FinancialAccountResponse]
    total: int
    offset: int
    limit: int


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
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    target_amount: Decimal | None = Field(
        default=None,
        gt=0,
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
        required_fields = {"name", "target_amount", "currency"}
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


class SavingsGoalListResponse(BaseModel):
    items: list[SavingsGoalResponse]
    total: int
    offset: int
    limit: int


class SavingsContributionCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    kind: SavingsContributionKind = SavingsContributionKind.CONTRIBUTION
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    occurred_on: date
    notes: str | None = Field(default=None, max_length=500)


class SavingsContributionUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    kind: SavingsContributionKind | None = None
    amount: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=18,
        decimal_places=2,
    )
    occurred_on: date | None = None
    notes: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        required_fields = {"kind", "amount", "occurred_on"}
        null_fields = {
            field
            for field in required_fields & self.model_fields_set
            if getattr(self, field) is None
        }
        if null_fields:
            fields = ", ".join(sorted(null_fields))
            raise ValueError(f"fields cannot be null: {fields}")
        return self


class SavingsContributionResponse(EntityResponse):
    goal_id: UUID
    kind: SavingsContributionKind
    amount: Decimal
    signed_amount: Decimal
    occurred_on: date
    notes: str | None


class SavingsContributionListResponse(BaseModel):
    items: list[SavingsContributionResponse]
    total: int
    offset: int
    limit: int


class SavingsContributionMutationResponse(BaseModel):
    contribution: SavingsContributionResponse
    goal_current_amount: Decimal
    goal_progress_percent: Decimal


class NetWorthSnapshotCapture(CurrencyModel):
    notes: str | None = Field(default=None, max_length=500)


class NetWorthSnapshotResponse(EntityResponse):
    recorded_at: datetime
    assets: Decimal
    liabilities: Decimal
    net_worth: Decimal
    currency: str
    notes: str | None


class NetWorthSnapshotListResponse(BaseModel):
    items: list[NetWorthSnapshotResponse]
    total: int
    offset: int
    limit: int


class WealthSummary(BaseModel):
    currency: str
    assets: Decimal
    liabilities: Decimal
    net_worth: Decimal
    savings: Decimal
    savings_goal_target: Decimal
    savings_goal_current: Decimal
