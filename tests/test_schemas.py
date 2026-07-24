from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.wealth import AccountType, NetWorthSnapshot, SavingsGoal
from app.schemas.finance import FinancialTransactionCreate
from app.schemas.health import NutritionLogCreate, WeightEntryCreate, WeightEntryUpdate
from app.schemas.wealth import FinancialAccountCreate, FinancialAccountUpdate
from app.schemas.workout import WorkoutSetCreate


def test_currency_is_normalized_and_savings_account_is_validated() -> None:
    account = FinancialAccountCreate(
        name="Emergency fund",
        account_type=AccountType.ASSET,
        category="cash",
        balance="1250.50",
        currency="usd",
        is_savings=True,
    )

    assert account.currency == "USD"
    assert account.balance == Decimal("1250.50")

    with pytest.raises(ValidationError):
        FinancialAccountCreate(
            name="Invalid savings debt",
            account_type=AccountType.LIABILITY,
            category="loan",
            balance="100",
            is_savings=True,
        )

    with pytest.raises(ValidationError):
        FinancialAccountCreate(
            name="   ",
            account_type=AccountType.ASSET,
            category="cash",
            balance="100",
        )

    with pytest.raises(ValidationError):
        FinancialAccountCreate(
            name="Cash",
            account_type=AccountType.ASSET,
            category="cash",
            balance="100",
            currency="ДОЛ",
        )


def test_wealth_calculations_remain_decimal_exact() -> None:
    snapshot = NetWorthSnapshot(
        assets=Decimal("10000.10"),
        liabilities=Decimal("2500.05"),
    )
    goal = SavingsGoal(
        target_amount=Decimal("3000.00"),
        current_amount=Decimal("750.00"),
    )

    assert snapshot.net_worth == Decimal("7500.05")
    assert goal.progress_percent == Decimal("25.00")


def test_health_measurements_reject_impossible_values() -> None:
    with pytest.raises(ValidationError):
        WeightEntryCreate(recorded_on=date(2026, 7, 24), weight_kg=0)

    with pytest.raises(ValidationError):
        NutritionLogCreate(recorded_on=date(2026, 7, 24), calories=-1)


def test_patch_schemas_reject_empty_payloads_and_null_required_fields() -> None:
    with pytest.raises(ValidationError):
        FinancialAccountUpdate()

    with pytest.raises(ValidationError):
        FinancialAccountUpdate(balance=None)

    with pytest.raises(ValidationError):
        WeightEntryUpdate(weight_kg=None)


def test_normalized_labels_are_length_checked_after_casefolding() -> None:
    with pytest.raises(ValidationError):
        FinancialTransactionCreate(
            kind="expense",
            amount="1.00",
            category="ß" * 100,
            occurred_on=date(2026, 7, 24),
        )

    with pytest.raises(ValidationError):
        WorkoutSetCreate(exercise="ß" * 200, set_number=1, reps=1)
