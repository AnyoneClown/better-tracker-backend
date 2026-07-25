import asyncio
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.api.dependencies import CurrentUserDep, SessionDep
from app.models.monobank import MonobankAccount, MonobankJar
from app.models.privatbank import PrivatBankAccount
from app.models.wealth import (
    AccountType,
    FinancialAccount,
    NetWorthSnapshot,
    SavingsContribution,
    SavingsContributionKind,
    SavingsGoal,
)
from app.schemas.wealth import (
    FinancialAccountCreate,
    FinancialAccountListResponse,
    FinancialAccountResponse,
    FinancialAccountUpdate,
    NetWorthSnapshotCapture,
    NetWorthSnapshotListResponse,
    NetWorthSnapshotResponse,
    SavingsContributionCreate,
    SavingsContributionListResponse,
    SavingsContributionMutationResponse,
    SavingsContributionResponse,
    SavingsContributionUpdate,
    SavingsGoalCreate,
    SavingsGoalListResponse,
    SavingsGoalResponse,
    SavingsGoalUpdate,
    WealthSummary,
)

router = APIRouter(prefix="/wealth", tags=["wealth"])
SERIALIZATION_RETRY_LIMIT = 6


def sqlstate(error: BaseException) -> str | None:
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


def normalize_currency(currency: str) -> str:
    if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="currency must contain exactly three letters",
        )
    return currency.upper()


async def commit_or_conflict(session: SessionDep, detail: str) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if sqlstate(exc) == "23505":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=detail,
            ) from exc
        raise


async def run_with_serialization_retry[T](
    session: SessionDep,
    operation: Callable[[], Awaitable[T]],
) -> T:
    """Retry a complete Cockroach transaction after SQLSTATE 40001."""
    for attempt in range(SERIALIZATION_RETRY_LIMIT):
        try:
            return await operation()
        except DBAPIError as exc:
            await session.rollback()
            if sqlstate(exc) != "40001" or attempt == SERIALIZATION_RETRY_LIMIT - 1:
                raise
            delay = random.uniform(0.005, 0.015) * (2**attempt)
            await asyncio.sleep(delay)
    raise RuntimeError("serialization retry loop exhausted")


async def get_account_or_404(
    session: SessionDep,
    account_id: UUID,
    user_id: UUID,
) -> FinancialAccount:
    account = await session.scalar(
        select(FinancialAccount).where(
            FinancialAccount.id == account_id,
            FinancialAccount.user_id == user_id,
        )
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="account not found"
        )
    return account


@router.post(
    "/accounts",
    response_model=FinancialAccountResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_account(
    payload: FinancialAccountCreate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> FinancialAccount:
    account = FinancialAccount(**payload.model_dump(), user_id=current_user.id)
    session.add(account)
    await commit_or_conflict(
        session, "an account with this name and currency already exists"
    )
    await session.refresh(account)
    return account


@router.get("/accounts", response_model=FinancialAccountListResponse)
async def list_accounts(
    session: SessionDep,
    current_user: CurrentUserDep,
    account_type: AccountType | None = None,
    currency: str | None = Query(
        default=None,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Za-z]{3}$",
    ),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> FinancialAccountListResponse:
    filters = [FinancialAccount.user_id == current_user.id]
    if account_type is not None:
        filters.append(FinancialAccount.account_type == account_type)
    if currency is not None:
        filters.append(FinancialAccount.currency == normalize_currency(currency))
    statement = (
        select(FinancialAccount)
        .where(*filters)
        .order_by(
            FinancialAccount.name,
            FinancialAccount.currency,
            FinancialAccount.id,
        )
        .limit(limit)
        .offset(offset)
    )
    accounts = list((await session.scalars(statement)).all())
    total = await session.scalar(
        select(func.count()).select_from(FinancialAccount).where(*filters)
    )
    return FinancialAccountListResponse(
        items=[
            FinancialAccountResponse.model_validate(account) for account in accounts
        ],
        total=total or 0,
        offset=offset,
        limit=limit,
    )


@router.get("/accounts/{account_id}", response_model=FinancialAccountResponse)
async def get_account(
    account_id: UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> FinancialAccount:
    return await get_account_or_404(session, account_id, current_user.id)


@router.patch("/accounts/{account_id}", response_model=FinancialAccountResponse)
async def update_account(
    account_id: UUID,
    payload: FinancialAccountUpdate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> FinancialAccount:
    account = await get_account_or_404(session, account_id, current_user.id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(account, field, value)
    if account.is_savings and account.account_type != AccountType.ASSET:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="a savings account must be an asset",
        )
    await commit_or_conflict(
        session, "an account with this name and currency already exists"
    )
    await session.refresh(account)
    return account


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> Response:
    account = await get_account_or_404(session, account_id, current_user.id)
    await session.delete(account)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def get_goal_or_404(
    session: SessionDep,
    goal_id: UUID,
    user_id: UUID,
) -> SavingsGoal:
    goal = await session.scalar(
        select(SavingsGoal).where(
            SavingsGoal.id == goal_id,
            SavingsGoal.user_id == user_id,
        )
    )
    if goal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="savings goal not found",
        )
    return goal


async def get_contribution_or_404(
    session: SessionDep,
    contribution_id: UUID,
    user_id: UUID,
) -> SavingsContribution:
    contribution = await session.scalar(
        select(SavingsContribution)
        .join(SavingsGoal, SavingsGoal.id == SavingsContribution.goal_id)
        .where(
            SavingsContribution.id == contribution_id,
            SavingsGoal.user_id == user_id,
        )
    )
    if contribution is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="savings contribution not found",
        )
    return contribution


def contribution_delta(
    kind: SavingsContributionKind,
    amount: Decimal,
) -> Decimal:
    if kind == SavingsContributionKind.CONTRIBUTION:
        return amount
    return -amount


def validate_date_range(start_date: date | None, end_date: date | None) -> None:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="start_date must be on or before end_date",
        )


def contribution_mutation_response(
    contribution: SavingsContribution,
    goal: SavingsGoal,
) -> SavingsContributionMutationResponse:
    return SavingsContributionMutationResponse(
        contribution=SavingsContributionResponse.model_validate(contribution),
        goal_current_amount=goal.current_amount,
        goal_progress_percent=goal.progress_percent,
    )


@router.post(
    "/savings-goals",
    response_model=SavingsGoalResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_savings_goal(
    payload: SavingsGoalCreate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> SavingsGoal:
    goal = SavingsGoal(**payload.model_dump(), user_id=current_user.id)
    session.add(goal)
    await commit_or_conflict(
        session, "a savings goal with this name and currency already exists"
    )
    await session.refresh(goal)
    return goal


@router.get("/savings-goals", response_model=SavingsGoalListResponse)
async def list_savings_goals(
    session: SessionDep,
    current_user: CurrentUserDep,
    currency: str | None = Query(
        default=None,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Za-z]{3}$",
    ),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> SavingsGoalListResponse:
    filters = [SavingsGoal.user_id == current_user.id]
    if currency is not None:
        filters.append(SavingsGoal.currency == normalize_currency(currency))
    statement = (
        select(SavingsGoal)
        .where(*filters)
        .order_by(
            SavingsGoal.target_date.asc().nulls_last(),
            SavingsGoal.name,
            SavingsGoal.currency,
            SavingsGoal.id,
        )
        .limit(limit)
        .offset(offset)
    )
    goals = list((await session.scalars(statement)).all())
    total = await session.scalar(
        select(func.count()).select_from(SavingsGoal).where(*filters)
    )
    return SavingsGoalListResponse(
        items=[SavingsGoalResponse.model_validate(goal) for goal in goals],
        total=total or 0,
        offset=offset,
        limit=limit,
    )


@router.get("/savings-goals/{goal_id}", response_model=SavingsGoalResponse)
async def get_savings_goal(
    goal_id: UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> SavingsGoal:
    return await get_goal_or_404(session, goal_id, current_user.id)


@router.patch("/savings-goals/{goal_id}", response_model=SavingsGoalResponse)
async def update_savings_goal(
    goal_id: UUID,
    payload: SavingsGoalUpdate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> SavingsGoal:
    goal = await get_goal_or_404(session, goal_id, current_user.id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(goal, field, value)
    await commit_or_conflict(
        session, "a savings goal with this name and currency already exists"
    )
    await session.refresh(goal)
    return goal


@router.delete("/savings-goals/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_savings_goal(
    goal_id: UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> Response:
    goal = await get_goal_or_404(session, goal_id, current_user.id)
    await session.delete(goal)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/savings-goals/{goal_id}/contributions",
    response_model=SavingsContributionMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_savings_contribution(
    goal_id: UUID,
    payload: SavingsContributionCreate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> SavingsContributionMutationResponse:
    async def operation() -> tuple[SavingsContribution, SavingsGoal]:
        goal = await get_goal_or_404(session, goal_id, current_user.id)
        new_amount = goal.current_amount + contribution_delta(
            payload.kind,
            payload.amount,
        )
        if new_amount < 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="withdrawal cannot exceed the savings goal's current amount",
            )

        contribution = SavingsContribution(goal_id=goal.id, **payload.model_dump())
        goal.current_amount = new_amount
        session.add(contribution)
        await session.commit()
        return contribution, goal

    contribution, goal = await run_with_serialization_retry(session, operation)
    return contribution_mutation_response(contribution, goal)


@router.get(
    "/savings-goals/{goal_id}/contributions",
    response_model=SavingsContributionListResponse,
)
async def list_savings_contributions(
    goal_id: UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> SavingsContributionListResponse:
    await get_goal_or_404(session, goal_id, current_user.id)
    validate_date_range(start_date, end_date)

    filters = [SavingsContribution.goal_id == goal_id]
    if start_date is not None:
        filters.append(SavingsContribution.occurred_on >= start_date)
    if end_date is not None:
        filters.append(SavingsContribution.occurred_on <= end_date)
    statement = (
        select(SavingsContribution)
        .where(*filters)
        .order_by(
            SavingsContribution.occurred_on.desc(),
            SavingsContribution.created_at.desc(),
            SavingsContribution.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    contributions = list((await session.scalars(statement)).all())
    total = await session.scalar(
        select(func.count()).select_from(SavingsContribution).where(*filters)
    )
    return SavingsContributionListResponse(
        items=[
            SavingsContributionResponse.model_validate(contribution)
            for contribution in contributions
        ],
        total=total or 0,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/savings-contributions/{contribution_id}",
    response_model=SavingsContributionResponse,
)
async def get_savings_contribution(
    contribution_id: UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> SavingsContribution:
    return await get_contribution_or_404(
        session,
        contribution_id,
        current_user.id,
    )


@router.patch(
    "/savings-contributions/{contribution_id}",
    response_model=SavingsContributionMutationResponse,
)
async def update_savings_contribution(
    contribution_id: UUID,
    payload: SavingsContributionUpdate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> SavingsContributionMutationResponse:
    async def operation() -> tuple[SavingsContribution, SavingsGoal]:
        contribution = await get_contribution_or_404(
            session,
            contribution_id,
            current_user.id,
        )
        goal = await get_goal_or_404(
            session,
            contribution.goal_id,
            current_user.id,
        )
        changes = payload.model_dump(exclude_unset=True)
        new_kind = changes.get("kind", contribution.kind)
        new_contribution_amount = changes.get("amount", contribution.amount)
        new_goal_amount = (
            goal.current_amount
            - contribution.signed_amount
            + contribution_delta(new_kind, new_contribution_amount)
        )
        if new_goal_amount < 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="withdrawal cannot exceed the savings goal's current amount",
            )

        for field, value in changes.items():
            setattr(contribution, field, value)
        goal.current_amount = new_goal_amount
        await session.commit()
        return contribution, goal

    contribution, goal = await run_with_serialization_retry(session, operation)
    return contribution_mutation_response(contribution, goal)


@router.delete(
    "/savings-contributions/{contribution_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_savings_contribution(
    contribution_id: UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> Response:
    async def operation() -> Response:
        contribution = await get_contribution_or_404(
            session,
            contribution_id,
            current_user.id,
        )
        goal = await get_goal_or_404(
            session,
            contribution.goal_id,
            current_user.id,
        )
        new_goal_amount = goal.current_amount - contribution.signed_amount
        if new_goal_amount < 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "deleting this contribution would make the goal balance negative"
                ),
            )

        goal.current_amount = new_goal_amount
        await session.delete(contribution)
        await session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return await run_with_serialization_retry(session, operation)


async def calculate_summary(
    session: SessionDep,
    currency: str,
    user_id: UUID,
) -> WealthSummary:
    currency = normalize_currency(currency)
    totals_statement = (
        select(FinancialAccount.account_type, func.sum(FinancialAccount.balance))
        .where(
            FinancialAccount.user_id == user_id,
            FinancialAccount.currency == currency,
            FinancialAccount.include_in_net_worth.is_(True),
        )
        .group_by(FinancialAccount.account_type)
    )
    totals = {
        account_type: Decimal(str(total))
        for account_type, total in (await session.execute(totals_statement)).all()
    }
    assets = totals.get(AccountType.ASSET, Decimal("0"))
    liabilities = totals.get(AccountType.LIABILITY, Decimal("0"))

    monobank_balances = list(
        (
            await session.scalars(
                select(MonobankAccount.balance).where(
                    MonobankAccount.user_id == user_id,
                    MonobankAccount.currency == currency,
                )
            )
        ).all()
    )
    jar_balances = list(
        (
            await session.scalars(
                select(MonobankJar.balance).where(
                    MonobankJar.user_id == user_id,
                    MonobankJar.currency == currency,
                )
            )
        ).all()
    )
    assets += sum(
        (Decimal(str(balance)) for balance in monobank_balances if balance > 0),
        Decimal("0"),
    )
    assets += sum((Decimal(str(balance)) for balance in jar_balances), Decimal("0"))
    liabilities += sum(
        (abs(Decimal(str(balance))) for balance in monobank_balances if balance < 0),
        Decimal("0"),
    )

    privatbank_balances = list(
        (
            await session.scalars(
                select(PrivatBankAccount.balance).where(
                    PrivatBankAccount.user_id == user_id,
                    PrivatBankAccount.currency == currency,
                )
            )
        ).all()
    )
    assets += sum(
        (Decimal(str(balance)) for balance in privatbank_balances if balance > 0),
        Decimal("0"),
    )
    liabilities += sum(
        (abs(Decimal(str(balance))) for balance in privatbank_balances if balance < 0),
        Decimal("0"),
    )

    savings = await session.scalar(
        select(func.sum(FinancialAccount.balance)).where(
            FinancialAccount.user_id == user_id,
            FinancialAccount.currency == currency,
            FinancialAccount.is_savings.is_(True),
        )
    )
    goal_totals = (
        await session.execute(
            select(
                func.sum(SavingsGoal.target_amount),
                func.sum(SavingsGoal.current_amount),
            ).where(
                SavingsGoal.user_id == user_id,
                SavingsGoal.currency == currency,
            )
        )
    ).one()
    local_savings = Decimal(str(savings)) if savings is not None else Decimal("0")
    monobank_savings = sum(
        (Decimal(str(balance)) for balance in jar_balances), Decimal("0")
    )
    return WealthSummary(
        currency=currency,
        assets=assets,
        liabilities=liabilities,
        net_worth=assets - liabilities,
        savings=local_savings + monobank_savings,
        savings_goal_target=(
            Decimal(str(goal_totals[0])) if goal_totals[0] is not None else Decimal("0")
        ),
        savings_goal_current=(
            Decimal(str(goal_totals[1])) if goal_totals[1] is not None else Decimal("0")
        ),
    )


@router.get("/summary", response_model=WealthSummary)
async def get_wealth_summary(
    session: SessionDep,
    current_user: CurrentUserDep,
    currency: str = Query(
        default="USD",
        min_length=3,
        max_length=3,
        pattern=r"^[A-Za-z]{3}$",
    ),
) -> WealthSummary:
    return await calculate_summary(session, currency, current_user.id)


@router.post(
    "/net-worth-snapshots/capture",
    response_model=NetWorthSnapshotResponse,
    status_code=status.HTTP_201_CREATED,
)
async def capture_net_worth_snapshot(
    payload: NetWorthSnapshotCapture,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> NetWorthSnapshot:
    summary = await calculate_summary(session, payload.currency, current_user.id)
    snapshot = NetWorthSnapshot(
        user_id=current_user.id,
        recorded_at=datetime.now(UTC),
        assets=summary.assets,
        liabilities=summary.liabilities,
        currency=summary.currency,
        notes=payload.notes,
    )
    session.add(snapshot)
    await session.commit()
    await session.refresh(snapshot)
    return snapshot


@router.get(
    "/net-worth-snapshots",
    response_model=NetWorthSnapshotListResponse,
)
async def list_net_worth_snapshots(
    session: SessionDep,
    current_user: CurrentUserDep,
    currency: str | None = Query(
        default=None,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Za-z]{3}$",
    ),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> NetWorthSnapshotListResponse:
    filters = [NetWorthSnapshot.user_id == current_user.id]
    if currency is not None:
        filters.append(NetWorthSnapshot.currency == normalize_currency(currency))
    statement = (
        select(NetWorthSnapshot)
        .where(*filters)
        .order_by(
            NetWorthSnapshot.recorded_at.desc(),
            NetWorthSnapshot.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    snapshots = list((await session.scalars(statement)).all())
    total = await session.scalar(
        select(func.count()).select_from(NetWorthSnapshot).where(*filters)
    )
    return NetWorthSnapshotListResponse(
        items=[
            NetWorthSnapshotResponse.model_validate(snapshot) for snapshot in snapshots
        ],
        total=total or 0,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/net-worth-snapshots/{snapshot_id}",
    response_model=NetWorthSnapshotResponse,
)
async def get_net_worth_snapshot(
    snapshot_id: UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> NetWorthSnapshot:
    snapshot = await session.scalar(
        select(NetWorthSnapshot).where(
            NetWorthSnapshot.id == snapshot_id,
            NetWorthSnapshot.user_id == current_user.id,
        )
    )
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="net worth snapshot not found",
        )
    return snapshot


@router.delete(
    "/net-worth-snapshots/{snapshot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_net_worth_snapshot(
    snapshot_id: UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> Response:
    snapshot = await session.scalar(
        select(NetWorthSnapshot).where(
            NetWorthSnapshot.id == snapshot_id,
            NetWorthSnapshot.user_id == current_user.id,
        )
    )
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="net worth snapshot not found",
        )
    await session.delete(snapshot)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
