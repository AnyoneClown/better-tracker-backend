import asyncio
from calendar import monthrange
from collections.abc import Awaitable, Callable
from datetime import date
from functools import partial
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.dependencies import CurrentUserDep, SessionDep
from app.api.routes.finance import (
    get_finance_summary,
    list_budgets,
    list_finance_currencies,
    list_transactions,
)
from app.api.routes.monobank import get_monobank_connection
from app.api.routes.wealth import (
    get_wealth_summary,
    list_accounts,
    list_net_worth_snapshots,
    list_savings_goals,
)
from app.cache import cache_response
from app.models.finance import TransactionKind
from app.models.wealth import SavingsContribution, SavingsGoal
from app.schemas.finance import (
    FinanceSummaryResponse,
    FinancialTransactionListResponse,
    MonthlyBudgetListResponse,
)
from app.schemas.money import MoneyWorkspaceResponse
from app.schemas.monobank import MonobankConnectionResponse
from app.schemas.wealth import (
    FinancialAccountListResponse,
    NetWorthSnapshotListResponse,
    SavingsContributionResponse,
    SavingsGoalListResponse,
    WealthSummary,
)

router = APIRouter(prefix="/money", tags=["money"])
WORKSPACE_LIMIT = 100
MonthQuery = Annotated[
    str,
    Query(min_length=7, max_length=7, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
]
CurrencyQuery = Annotated[
    str,
    Query(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$"),
]


def _session_factory(
    session: AsyncSession,
) -> async_sessionmaker[AsyncSession]:
    if session.bind is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database session is unavailable.",
        )
    return async_sessionmaker(
        bind=session.bind,
        class_=AsyncSession,
        autoflush=False,
        expire_on_commit=False,
    )


async def _load[T](
    factory: async_sessionmaker[AsyncSession],
    operation: Callable[[AsyncSession], Awaitable[T]],
) -> T:
    async with factory() as session:
        return await operation(session)


def _month_range(start_month: str, end_month: str) -> list[tuple[int, int]]:
    start_year, start = map(int, start_month.split("-"))
    end_year, end = map(int, end_month.split("-"))
    first = start_year * 12 + start - 1
    last = end_year * 12 + end - 1
    if start_year < 1 or end_year > 9999 or last < first or last - first >= 12:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Choose a contiguous range of up to 12 months.",
        )
    return [divmod(value, 12) for value in range(first, last + 1)]


async def _list_workspace_contributions(
    session: AsyncSession,
    user_id: UUID,
    currency: str,
    start_date: date,
    end_date: date,
) -> list[SavingsContributionResponse]:
    eligible_goal_ids = (
        select(SavingsGoal.id)
        .where(
            SavingsGoal.user_id == user_id,
            SavingsGoal.currency == currency,
        )
        .order_by(
            SavingsGoal.target_date.asc().nulls_last(),
            SavingsGoal.name,
            SavingsGoal.currency,
            SavingsGoal.id,
        )
        .limit(WORKSPACE_LIMIT)
    )
    contributions = list(
        (
            await session.scalars(
                select(SavingsContribution)
                .join(SavingsGoal, SavingsGoal.id == SavingsContribution.goal_id)
                .where(
                    SavingsContribution.goal_id.in_(eligible_goal_ids),
                    SavingsContribution.occurred_on >= start_date,
                    SavingsContribution.occurred_on <= end_date,
                )
                .order_by(
                    SavingsGoal.target_date.asc().nulls_last(),
                    SavingsGoal.name,
                    SavingsGoal.currency,
                    SavingsGoal.id,
                    SavingsContribution.occurred_on.desc(),
                    SavingsContribution.created_at.desc(),
                    SavingsContribution.id.desc(),
                )
            )
        ).all()
    )

    # ponytail: one monthly scan replaces N goal queries; use a windowed query if
    # more than 100 contributions per goal/month becomes a real workload.
    per_goal: dict[UUID, int] = {}
    result: list[SavingsContributionResponse] = []
    for contribution in contributions:
        count = per_goal.get(contribution.goal_id, 0)
        if count >= WORKSPACE_LIMIT:
            continue
        per_goal[contribution.goal_id] = count + 1
        result.append(SavingsContributionResponse.model_validate(contribution))
    return result


@router.get("/workspace", response_model=MoneyWorkspaceResponse)
@cache_response
async def get_money_workspace(
    session: SessionDep,
    current_user: CurrentUserDep,
    year: Annotated[int, Query(ge=1, le=9999)],
    month: Annotated[int, Query(ge=1, le=12)],
    currency: CurrencyQuery = "UAH",
    include_ignored: bool = False,
    category: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
) -> MoneyWorkspaceResponse:
    currency = currency.upper()
    period_start = date(year, month, 1)
    period_end = date(year, month, monthrange(year, month)[1])
    factory = _session_factory(session)

    (
        finance,
        transactions,
        budgets,
        wealth,
        accounts,
        goals,
        contributions,
        snapshots,
        currencies,
        monobank,
    ) = await asyncio.gather(
        _load(
            factory,
            partial(
                get_finance_summary,
                current_user=current_user,
                year=year,
                month=month,
                currency=currency,
            ),
        ),
        _load(
            factory,
            partial(
                list_transactions,
                current_user=current_user,
                kind=TransactionKind.EXPENSE if category else None,
                source=None,
                category=category,
                currency=currency,
                start_date=period_start,
                end_date=period_end,
                include_ignored=include_ignored,
                offset=0,
                limit=WORKSPACE_LIMIT,
            ),
        ),
        _load(
            factory,
            partial(
                list_budgets,
                current_user=current_user,
                year=year,
                month=month,
                category=None,
                currency=currency,
                offset=0,
                limit=WORKSPACE_LIMIT,
            ),
        ),
        _load(
            factory,
            partial(
                get_wealth_summary,
                current_user=current_user,
                currency=currency,
            ),
        ),
        _load(
            factory,
            partial(
                list_accounts,
                current_user=current_user,
                account_type=None,
                currency=currency,
                limit=WORKSPACE_LIMIT,
                offset=0,
            ),
        ),
        _load(
            factory,
            partial(
                list_savings_goals,
                current_user=current_user,
                currency=currency,
                limit=WORKSPACE_LIMIT,
                offset=0,
            ),
        ),
        _load(
            factory,
            partial(
                _list_workspace_contributions,
                user_id=current_user.id,
                currency=currency,
                start_date=period_start,
                end_date=period_end,
            ),
        ),
        _load(
            factory,
            partial(
                list_net_worth_snapshots,
                current_user=current_user,
                currency=currency,
                limit=WORKSPACE_LIMIT,
                offset=0,
            ),
        ),
        _load(factory, partial(list_finance_currencies, current_user=current_user)),
        _load(factory, partial(get_monobank_connection, current_user=current_user)),
    )

    return MoneyWorkspaceResponse(
        finance=FinanceSummaryResponse.model_validate(finance),
        transactions=FinancialTransactionListResponse.model_validate(
            transactions
        ).items,
        budgets=MonthlyBudgetListResponse.model_validate(budgets).items,
        wealth=WealthSummary.model_validate(wealth),
        accounts=FinancialAccountListResponse.model_validate(accounts).items,
        goals=SavingsGoalListResponse.model_validate(goals).items,
        contributions=contributions,
        snapshots=NetWorthSnapshotListResponse.model_validate(snapshots).items,
        currencies=currencies,
        monobank=MonobankConnectionResponse.model_validate(monobank),
    )


@router.get("/summaries", response_model=list[FinanceSummaryResponse])
@cache_response
async def get_money_summaries(
    session: SessionDep,
    current_user: CurrentUserDep,
    start_month: MonthQuery,
    end_month: MonthQuery,
    currency: CurrencyQuery = "UAH",
) -> list[FinanceSummaryResponse]:
    factory = _session_factory(session)
    summaries = await asyncio.gather(
        *(
            _load(
                factory,
                partial(
                    get_finance_summary,
                    current_user=current_user,
                    year=year,
                    month=month + 1,
                    currency=currency.upper(),
                ),
            )
            for year, month in _month_range(start_month, end_month)
        ),
    )
    return [FinanceSummaryResponse.model_validate(summary) for summary in summaries]
