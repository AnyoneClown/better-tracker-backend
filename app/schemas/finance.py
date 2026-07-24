from datetime import date
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.finance import TransactionKind
from app.schemas.common import EntityResponse


class FinanceInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("currency", check_fields=False)
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None


class FinancialTransactionCreate(FinanceInput):
    kind: TransactionKind
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    category: str = Field(min_length=1, max_length=100)
    occurred_on: date
    currency: str = Field(
        default="USD", min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$"
    )
    description: str | None = Field(default=None, max_length=500)


class FinancialTransactionUpdate(FinanceInput):
    kind: TransactionKind | None = None
    amount: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=18,
        decimal_places=2,
    )
    category: str | None = Field(default=None, min_length=1, max_length=100)
    occurred_on: date | None = None
    currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Za-z]{3}$",
    )
    description: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")

        non_nullable = {"kind", "amount", "category", "occurred_on", "currency"}
        null_fields = {
            field
            for field in non_nullable & self.model_fields_set
            if getattr(self, field) is None
        }
        if null_fields:
            fields = ", ".join(sorted(null_fields))
            raise ValueError(f"fields cannot be null: {fields}")
        return self


class FinancialTransactionResponse(EntityResponse):
    kind: TransactionKind
    amount: Decimal
    category: str
    occurred_on: date
    currency: str
    description: str | None


class FinancialTransactionListResponse(BaseModel):
    items: list[FinancialTransactionResponse]
    total: int
    offset: int
    limit: int


class MonthlyBudgetCreate(FinanceInput):
    year: int = Field(ge=1, le=9999)
    month: int = Field(ge=1, le=12)
    category: str = Field(min_length=1, max_length=100)
    currency: str = Field(
        default="USD", min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$"
    )
    limit_amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)


class MonthlyBudgetUpdate(FinanceInput):
    year: int | None = Field(default=None, ge=1, le=9999)
    month: int | None = Field(default=None, ge=1, le=12)
    category: str | None = Field(default=None, min_length=1, max_length=100)
    currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Za-z]{3}$",
    )
    limit_amount: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=18,
        decimal_places=2,
    )

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        null_fields = {
            field for field in self.model_fields_set if getattr(self, field) is None
        }
        if null_fields:
            fields = ", ".join(sorted(null_fields))
            raise ValueError(f"fields cannot be null: {fields}")
        return self


class MonthlyBudgetResponse(EntityResponse):
    year: int
    month: int
    category: str
    currency: str
    limit_amount: Decimal


class MonthlyBudgetListResponse(BaseModel):
    items: list[MonthlyBudgetResponse]
    total: int
    offset: int
    limit: int


class FinanceCategorySummary(BaseModel):
    category: str
    income: Decimal
    expenses: Decimal
    net: Decimal
    budget: Decimal | None
    budget_remaining: Decimal | None


class FinanceSummaryResponse(BaseModel):
    year: int
    month: int
    currency: str
    total_income: Decimal
    total_expenses: Decimal
    net: Decimal
    total_budget: Decimal
    budget_remaining: Decimal
    categories: list[FinanceCategorySummary]
