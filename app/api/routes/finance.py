from calendar import monthrange
from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import CurrentUserDep, SessionDep
from app.models.finance import (
    FinancialTransaction,
    MonthlyBudget,
    TransactionKind,
    TransactionSource,
)
from app.models.monobank import MonobankAccount, MonobankJar
from app.models.wealth import FinancialAccount, SavingsGoal
from app.schemas.finance import (
    FinanceCategorySummary,
    FinanceSummaryResponse,
    FinancialTransactionCreate,
    FinancialTransactionListResponse,
    FinancialTransactionResponse,
    FinancialTransactionUpdate,
    MonthlyBudgetCreate,
    MonthlyBudgetListResponse,
    MonthlyBudgetResponse,
    MonthlyBudgetUpdate,
)

router = APIRouter(prefix="/finance", tags=["finance"])
BUDGET_CONFLICT_DETAIL = (
    "A budget already exists for this period, category, and currency"
)

Offset = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=100)]
CurrencyQuery = Annotated[
    str,
    Query(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$"),
]


def _sqlstate(error: BaseException) -> str | None:
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        for attribute in ("sqlstate", "pgcode"):
            value = getattr(current, attribute, None)
            if isinstance(value, str):
                return value
        nested = getattr(current, "orig", None) or current.__cause__
        current = nested if isinstance(nested, BaseException) else None
    return None


def _normalize_category(category: str) -> str:
    return " ".join(category.split()).casefold()


async def _commit(session: SessionDep, *, conflict_detail: str) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if _sqlstate(exc) == "23505":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=conflict_detail,
            ) from exc
        raise


async def _get_transaction_or_404(
    transaction_id: UUID,
    session: SessionDep,
    user_id: UUID,
) -> FinancialTransaction:
    transaction = await session.scalar(
        select(FinancialTransaction).where(
            FinancialTransaction.id == transaction_id,
            FinancialTransaction.user_id == user_id,
        )
    )
    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Financial transaction not found",
        )
    return transaction


async def _get_budget_or_404(
    budget_id: UUID,
    session: SessionDep,
    user_id: UUID,
) -> MonthlyBudget:
    budget = await session.scalar(
        select(MonthlyBudget).where(
            MonthlyBudget.id == budget_id,
            MonthlyBudget.user_id == user_id,
        )
    )
    if budget is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Monthly budget not found",
        )
    return budget


@router.get("/summary", response_model=FinanceSummaryResponse)
async def get_finance_summary(
    session: SessionDep,
    current_user: CurrentUserDep,
    year: Annotated[int, Query(ge=1, le=9999)],
    month: Annotated[int, Query(ge=1, le=12)],
    currency: CurrencyQuery = "USD",
) -> FinanceSummaryResponse:
    currency = currency.upper()
    period_start = date(year, month, 1)
    period_end = date(year, month, monthrange(year, month)[1])

    transaction_rows = (
        await session.execute(
            select(
                FinancialTransaction.category,
                FinancialTransaction.kind,
                func.sum(FinancialTransaction.amount),
            )
            .where(
                FinancialTransaction.user_id == current_user.id,
                FinancialTransaction.currency == currency,
                FinancialTransaction.occurred_on >= period_start,
                FinancialTransaction.occurred_on <= period_end,
                FinancialTransaction.hold.is_(False),
                FinancialTransaction.excluded_from_summary.is_(False),
            )
            .group_by(FinancialTransaction.category, FinancialTransaction.kind)
        )
    ).all()
    budget_rows = (
        await session.execute(
            select(MonthlyBudget.category, func.sum(MonthlyBudget.limit_amount))
            .where(
                MonthlyBudget.user_id == current_user.id,
                MonthlyBudget.year == year,
                MonthlyBudget.month == month,
                MonthlyBudget.currency == currency,
            )
            .group_by(MonthlyBudget.category)
        )
    ).all()

    zero = Decimal("0.00")
    income_by_category: dict[str, Decimal] = {}
    expenses_by_category: dict[str, Decimal] = {}
    for category, kind, amount in transaction_rows:
        if kind in (TransactionKind.INCOME, TransactionKind.INCOME.value):
            income_by_category[category] = amount
        else:
            expenses_by_category[category] = amount

    budgets_by_category = {category: amount for category, amount in budget_rows}
    category_names = sorted(
        income_by_category.keys()
        | expenses_by_category.keys()
        | budgets_by_category.keys()
    )
    categories: list[FinanceCategorySummary] = []
    for category in category_names:
        income = income_by_category.get(category, zero)
        expenses = expenses_by_category.get(category, zero)
        budget = budgets_by_category.get(category)
        categories.append(
            FinanceCategorySummary(
                category=category,
                income=income,
                expenses=expenses,
                net=income - expenses,
                budget=budget,
                budget_remaining=budget - expenses if budget is not None else None,
            )
        )

    total_income = sum(income_by_category.values(), zero)
    total_expenses = sum(expenses_by_category.values(), zero)
    total_budget = sum(budgets_by_category.values(), zero)
    return FinanceSummaryResponse(
        year=year,
        month=month,
        currency=currency,
        total_income=total_income,
        total_expenses=total_expenses,
        net=total_income - total_expenses,
        total_budget=total_budget,
        budget_remaining=total_budget - total_expenses,
        categories=categories,
    )


@router.post(
    "/transactions",
    response_model=FinancialTransactionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_transaction(
    payload: FinancialTransactionCreate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> FinancialTransaction:
    transaction = FinancialTransaction(
        **payload.model_dump(),
        user_id=current_user.id,
    )
    session.add(transaction)
    await _commit(session, conflict_detail="Financial transaction already exists")
    await session.refresh(transaction)
    return transaction


@router.get("/transactions", response_model=FinancialTransactionListResponse)
async def list_transactions(
    session: SessionDep,
    current_user: CurrentUserDep,
    kind: TransactionKind | None = None,
    source: TransactionSource | None = None,
    category: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    currency: Annotated[
        str | None,
        Query(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$"),
    ] = None,
    start_date: date | None = None,
    end_date: date | None = None,
    offset: Offset = 0,
    limit: Limit = 50,
) -> FinancialTransactionListResponse:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="start_date must be on or before end_date",
        )

    filters = [FinancialTransaction.user_id == current_user.id]
    if kind is not None:
        filters.append(FinancialTransaction.kind == kind)
    if source is not None:
        filters.append(FinancialTransaction.source == source)
    if category is not None:
        filters.append(FinancialTransaction.category == _normalize_category(category))
    if currency is not None:
        filters.append(FinancialTransaction.currency == currency.upper())
    if start_date is not None:
        filters.append(FinancialTransaction.occurred_on >= start_date)
    if end_date is not None:
        filters.append(FinancialTransaction.occurred_on <= end_date)

    query: Select[tuple[FinancialTransaction]] = select(FinancialTransaction).where(
        *filters
    )
    transactions = (
        (
            await session.execute(
                query.order_by(
                    FinancialTransaction.occurred_on.desc(),
                    FinancialTransaction.occurred_at.desc().nulls_last(),
                    FinancialTransaction.created_at.desc(),
                    FinancialTransaction.id.desc(),
                )
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    total = await session.scalar(
        select(func.count()).select_from(FinancialTransaction).where(*filters)
    )
    return FinancialTransactionListResponse(
        items=[
            FinancialTransactionResponse.model_validate(transaction)
            for transaction in transactions
        ],
        total=total or 0,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/transactions/{transaction_id}",
    response_model=FinancialTransactionResponse,
)
async def get_transaction(
    transaction_id: UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> FinancialTransaction:
    return await _get_transaction_or_404(
        transaction_id,
        session,
        current_user.id,
    )


@router.patch(
    "/transactions/{transaction_id}",
    response_model=FinancialTransactionResponse,
)
async def update_transaction(
    transaction_id: UUID,
    payload: FinancialTransactionUpdate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> FinancialTransaction:
    transaction = await _get_transaction_or_404(
        transaction_id,
        session,
        current_user.id,
    )
    changes = payload.model_dump(exclude_unset=True)
    if transaction.source == TransactionSource.MONOBANK:
        allowed_fields = {"category", "excluded_from_summary"}
        immutable_fields = set(changes) - allowed_fields
        if immutable_fields:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Monobank transactions only allow category and exclusion changes"
                ),
            )
        if "category" in changes:
            transaction.category_override = changes["category"]
            transaction.category = changes["category"]
        if "excluded_from_summary" in changes:
            transaction.excluded_from_summary = changes["excluded_from_summary"]
    else:
        for field, value in changes.items():
            setattr(transaction, field, value)

    await _commit(session, conflict_detail="Financial transaction already exists")
    await session.refresh(transaction)
    return transaction


@router.delete(
    "/transactions/{transaction_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_transaction(
    transaction_id: UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> Response:
    transaction = await _get_transaction_or_404(
        transaction_id,
        session,
        current_user.id,
    )
    if transaction.source == TransactionSource.MONOBANK:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Monobank transactions cannot be deleted",
        )
    await session.delete(transaction)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/currencies", response_model=list[str])
async def list_finance_currencies(
    session: SessionDep,
    current_user: CurrentUserDep,
) -> list[str]:
    model_columns = (
        (FinancialTransaction, FinancialTransaction.currency),
        (MonthlyBudget, MonthlyBudget.currency),
        (FinancialAccount, FinancialAccount.currency),
        (SavingsGoal, SavingsGoal.currency),
        (MonobankAccount, MonobankAccount.currency),
        (MonobankJar, MonobankJar.currency),
    )
    currencies: set[str] = set()
    for model, column in model_columns:
        currencies.update(
            (
                await session.scalars(
                    select(column).where(model.user_id == current_user.id).distinct()
                )
            ).all()
        )
    return sorted(currencies, key=lambda currency: (currency != "UAH", currency))


@router.post(
    "/budgets",
    response_model=MonthlyBudgetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_budget(
    payload: MonthlyBudgetCreate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> MonthlyBudget:
    budget = MonthlyBudget(**payload.model_dump(), user_id=current_user.id)
    session.add(budget)
    await _commit(
        session,
        conflict_detail=BUDGET_CONFLICT_DETAIL,
    )
    await session.refresh(budget)
    return budget


@router.get("/budgets", response_model=MonthlyBudgetListResponse)
async def list_budgets(
    session: SessionDep,
    current_user: CurrentUserDep,
    year: Annotated[int | None, Query(ge=1, le=9999)] = None,
    month: Annotated[int | None, Query(ge=1, le=12)] = None,
    category: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    currency: Annotated[
        str | None,
        Query(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$"),
    ] = None,
    offset: Offset = 0,
    limit: Limit = 50,
) -> MonthlyBudgetListResponse:
    filters = [MonthlyBudget.user_id == current_user.id]
    if year is not None:
        filters.append(MonthlyBudget.year == year)
    if month is not None:
        filters.append(MonthlyBudget.month == month)
    if category is not None:
        filters.append(MonthlyBudget.category == _normalize_category(category))
    if currency is not None:
        filters.append(MonthlyBudget.currency == currency.upper())

    query: Select[tuple[MonthlyBudget]] = select(MonthlyBudget).where(*filters)
    budgets = (
        (
            await session.execute(
                query.order_by(
                    MonthlyBudget.year.desc(),
                    MonthlyBudget.month.desc(),
                    MonthlyBudget.category,
                    MonthlyBudget.currency,
                    MonthlyBudget.id,
                )
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    total = await session.scalar(
        select(func.count()).select_from(MonthlyBudget).where(*filters)
    )
    return MonthlyBudgetListResponse(
        items=[MonthlyBudgetResponse.model_validate(budget) for budget in budgets],
        total=total or 0,
        offset=offset,
        limit=limit,
    )


@router.get("/budgets/{budget_id}", response_model=MonthlyBudgetResponse)
async def get_budget(
    budget_id: UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> MonthlyBudget:
    return await _get_budget_or_404(budget_id, session, current_user.id)


@router.patch("/budgets/{budget_id}", response_model=MonthlyBudgetResponse)
async def update_budget(
    budget_id: UUID,
    payload: MonthlyBudgetUpdate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> MonthlyBudget:
    budget = await _get_budget_or_404(budget_id, session, current_user.id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(budget, field, value)

    await _commit(
        session,
        conflict_detail=BUDGET_CONFLICT_DETAIL,
    )
    await session.refresh(budget)
    return budget


@router.delete(
    "/budgets/{budget_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_budget(
    budget_id: UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> Response:
    budget = await _get_budget_or_404(budget_id, session, current_user.id)
    await session.delete(budget)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
