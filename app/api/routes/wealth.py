from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import SessionDep
from app.models.wealth import (
    AccountType,
    FinancialAccount,
    NetWorthSnapshot,
    SavingsGoal,
)
from app.schemas.wealth import (
    FinancialAccountCreate,
    FinancialAccountResponse,
    FinancialAccountUpdate,
    NetWorthSnapshotCapture,
    NetWorthSnapshotResponse,
    SavingsGoalCreate,
    SavingsGoalResponse,
    SavingsGoalUpdate,
    WealthSummary,
)

router = APIRouter(prefix="/wealth", tags=["wealth"])


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


async def get_account_or_404(session: SessionDep, account_id: UUID) -> FinancialAccount:
    account = await session.get(FinancialAccount, account_id)
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
) -> FinancialAccount:
    account = FinancialAccount(**payload.model_dump())
    session.add(account)
    await commit_or_conflict(
        session, "an account with this name and currency already exists"
    )
    await session.refresh(account)
    return account


@router.get("/accounts", response_model=list[FinancialAccountResponse])
async def list_accounts(
    session: SessionDep,
    account_type: AccountType | None = None,
    currency: str | None = Query(
        default=None,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Za-z]{3}$",
    ),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[FinancialAccount]:
    statement = select(FinancialAccount)
    if account_type is not None:
        statement = statement.where(FinancialAccount.account_type == account_type)
    if currency is not None:
        statement = statement.where(
            FinancialAccount.currency == normalize_currency(currency)
        )
    statement = statement.order_by(FinancialAccount.name).limit(limit).offset(offset)
    return list((await session.scalars(statement)).all())


@router.get("/accounts/{account_id}", response_model=FinancialAccountResponse)
async def get_account(account_id: UUID, session: SessionDep) -> FinancialAccount:
    return await get_account_or_404(session, account_id)


@router.patch("/accounts/{account_id}", response_model=FinancialAccountResponse)
async def update_account(
    account_id: UUID,
    payload: FinancialAccountUpdate,
    session: SessionDep,
) -> FinancialAccount:
    account = await get_account_or_404(session, account_id)
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
async def delete_account(account_id: UUID, session: SessionDep) -> Response:
    account = await get_account_or_404(session, account_id)
    await session.delete(account)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def get_goal_or_404(session: SessionDep, goal_id: UUID) -> SavingsGoal:
    goal = await session.get(SavingsGoal, goal_id)
    if goal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="savings goal not found",
        )
    return goal


@router.post(
    "/savings-goals",
    response_model=SavingsGoalResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_savings_goal(
    payload: SavingsGoalCreate,
    session: SessionDep,
) -> SavingsGoal:
    goal = SavingsGoal(**payload.model_dump())
    session.add(goal)
    await commit_or_conflict(
        session, "a savings goal with this name and currency already exists"
    )
    await session.refresh(goal)
    return goal


@router.get("/savings-goals", response_model=list[SavingsGoalResponse])
async def list_savings_goals(
    session: SessionDep,
    currency: str | None = Query(
        default=None,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Za-z]{3}$",
    ),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[SavingsGoal]:
    statement = select(SavingsGoal)
    if currency is not None:
        statement = statement.where(
            SavingsGoal.currency == normalize_currency(currency)
        )
    statement = (
        statement.order_by(SavingsGoal.target_date, SavingsGoal.name)
        .limit(limit)
        .offset(offset)
    )
    return list((await session.scalars(statement)).all())


@router.get("/savings-goals/{goal_id}", response_model=SavingsGoalResponse)
async def get_savings_goal(goal_id: UUID, session: SessionDep) -> SavingsGoal:
    return await get_goal_or_404(session, goal_id)


@router.patch("/savings-goals/{goal_id}", response_model=SavingsGoalResponse)
async def update_savings_goal(
    goal_id: UUID,
    payload: SavingsGoalUpdate,
    session: SessionDep,
) -> SavingsGoal:
    goal = await get_goal_or_404(session, goal_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(goal, field, value)
    await commit_or_conflict(
        session, "a savings goal with this name and currency already exists"
    )
    await session.refresh(goal)
    return goal


@router.delete("/savings-goals/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_savings_goal(goal_id: UUID, session: SessionDep) -> Response:
    goal = await get_goal_or_404(session, goal_id)
    await session.delete(goal)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def calculate_summary(session: SessionDep, currency: str) -> WealthSummary:
    currency = normalize_currency(currency)
    totals_statement = (
        select(FinancialAccount.account_type, func.sum(FinancialAccount.balance))
        .where(
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

    savings = await session.scalar(
        select(func.sum(FinancialAccount.balance)).where(
            FinancialAccount.currency == currency,
            FinancialAccount.is_savings.is_(True),
        )
    )
    goal_totals = (
        await session.execute(
            select(
                func.sum(SavingsGoal.target_amount),
                func.sum(SavingsGoal.current_amount),
            ).where(SavingsGoal.currency == currency)
        )
    ).one()
    return WealthSummary(
        currency=currency,
        assets=assets,
        liabilities=liabilities,
        net_worth=assets - liabilities,
        savings=Decimal(str(savings)) if savings is not None else Decimal("0"),
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
    currency: str = Query(
        default="USD",
        min_length=3,
        max_length=3,
        pattern=r"^[A-Za-z]{3}$",
    ),
) -> WealthSummary:
    return await calculate_summary(session, currency)


@router.post(
    "/net-worth-snapshots/capture",
    response_model=NetWorthSnapshotResponse,
    status_code=status.HTTP_201_CREATED,
)
async def capture_net_worth_snapshot(
    payload: NetWorthSnapshotCapture,
    session: SessionDep,
) -> NetWorthSnapshot:
    summary = await calculate_summary(session, payload.currency)
    snapshot = NetWorthSnapshot(
        recorded_at=payload.recorded_at or datetime.now(UTC),
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
    response_model=list[NetWorthSnapshotResponse],
)
async def list_net_worth_snapshots(
    session: SessionDep,
    currency: str | None = Query(
        default=None,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Za-z]{3}$",
    ),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[NetWorthSnapshot]:
    statement = select(NetWorthSnapshot)
    if currency is not None:
        statement = statement.where(
            NetWorthSnapshot.currency == normalize_currency(currency)
        )
    statement = (
        statement.order_by(NetWorthSnapshot.recorded_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list((await session.scalars(statement)).all())


@router.delete(
    "/net-worth-snapshots/{snapshot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_net_worth_snapshot(
    snapshot_id: UUID,
    session: SessionDep,
) -> Response:
    snapshot = await session.get(NetWorthSnapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="net worth snapshot not found",
        )
    await session.delete(snapshot)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
