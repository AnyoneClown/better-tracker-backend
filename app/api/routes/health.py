from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import CurrentUserDep, SessionDep
from app.models.health import NutritionLog, WeightEntry
from app.schemas.health import (
    HealthSummary,
    NutritionLogCreate,
    NutritionLogListResponse,
    NutritionLogResponse,
    NutritionLogUpdate,
    WeightEntryCreate,
    WeightEntryListResponse,
    WeightEntryResponse,
    WeightEntryUpdate,
)

router = APIRouter(prefix="/health", tags=["health tracking"])


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


def validate_date_range(start_date: date | None, end_date: date | None) -> None:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="start_date must be on or before end_date",
        )


async def commit_unique_date(session: SessionDep, detail: str) -> None:
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


async def get_weight_or_404(
    session: SessionDep,
    entry_id: UUID,
    user_id: UUID,
) -> WeightEntry:
    entry = await session.scalar(
        select(WeightEntry).where(
            WeightEntry.id == entry_id,
            WeightEntry.user_id == user_id,
        )
    )
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="weight entry not found",
        )
    return entry


@router.post(
    "/weights",
    response_model=WeightEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_weight_entry(
    payload: WeightEntryCreate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> WeightEntry:
    entry = WeightEntry(**payload.model_dump(), user_id=current_user.id)
    session.add(entry)
    await commit_unique_date(session, "a weight entry already exists for this date")
    await session.refresh(entry)
    return entry


@router.get("/weights", response_model=WeightEntryListResponse)
async def list_weight_entries(
    session: SessionDep,
    current_user: CurrentUserDep,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> WeightEntryListResponse:
    validate_date_range(start_date, end_date)
    filters = [WeightEntry.user_id == current_user.id]
    if start_date is not None:
        filters.append(WeightEntry.recorded_on >= start_date)
    if end_date is not None:
        filters.append(WeightEntry.recorded_on <= end_date)
    statement = (
        select(WeightEntry)
        .where(*filters)
        .order_by(WeightEntry.recorded_on.desc(), WeightEntry.id.desc())
        .limit(limit)
        .offset(offset)
    )
    entries = list((await session.scalars(statement)).all())
    total = await session.scalar(
        select(func.count()).select_from(WeightEntry).where(*filters)
    )
    return WeightEntryListResponse(
        items=[WeightEntryResponse.model_validate(entry) for entry in entries],
        total=total or 0,
        offset=offset,
        limit=limit,
    )


@router.get("/weights/{entry_id}", response_model=WeightEntryResponse)
async def get_weight_entry(
    entry_id: UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> WeightEntry:
    return await get_weight_or_404(session, entry_id, current_user.id)


@router.patch("/weights/{entry_id}", response_model=WeightEntryResponse)
async def update_weight_entry(
    entry_id: UUID,
    payload: WeightEntryUpdate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> WeightEntry:
    entry = await get_weight_or_404(session, entry_id, current_user.id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(entry, field, value)
    await commit_unique_date(session, "a weight entry already exists for this date")
    await session.refresh(entry)
    return entry


@router.delete("/weights/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_weight_entry(
    entry_id: UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> Response:
    entry = await get_weight_or_404(session, entry_id, current_user.id)
    await session.delete(entry)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def get_nutrition_or_404(
    session: SessionDep,
    log_id: UUID,
    user_id: UUID,
) -> NutritionLog:
    log = await session.scalar(
        select(NutritionLog).where(
            NutritionLog.id == log_id,
            NutritionLog.user_id == user_id,
        )
    )
    if log is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="nutrition log not found",
        )
    return log


@router.post(
    "/nutrition",
    response_model=NutritionLogResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_nutrition_log(
    payload: NutritionLogCreate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> NutritionLog:
    log = NutritionLog(**payload.model_dump(), user_id=current_user.id)
    session.add(log)
    await commit_unique_date(session, "a nutrition log already exists for this date")
    await session.refresh(log)
    return log


@router.get("/nutrition", response_model=NutritionLogListResponse)
async def list_nutrition_logs(
    session: SessionDep,
    current_user: CurrentUserDep,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> NutritionLogListResponse:
    validate_date_range(start_date, end_date)
    filters = [NutritionLog.user_id == current_user.id]
    if start_date is not None:
        filters.append(NutritionLog.recorded_on >= start_date)
    if end_date is not None:
        filters.append(NutritionLog.recorded_on <= end_date)
    statement = (
        select(NutritionLog)
        .where(*filters)
        .order_by(NutritionLog.recorded_on.desc(), NutritionLog.id.desc())
        .limit(limit)
        .offset(offset)
    )
    logs = list((await session.scalars(statement)).all())
    total = await session.scalar(
        select(func.count()).select_from(NutritionLog).where(*filters)
    )
    return NutritionLogListResponse(
        items=[NutritionLogResponse.model_validate(log) for log in logs],
        total=total or 0,
        offset=offset,
        limit=limit,
    )


@router.get("/nutrition/{log_id}", response_model=NutritionLogResponse)
async def get_nutrition_log(
    log_id: UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> NutritionLog:
    return await get_nutrition_or_404(session, log_id, current_user.id)


@router.patch("/nutrition/{log_id}", response_model=NutritionLogResponse)
async def update_nutrition_log(
    log_id: UUID,
    payload: NutritionLogUpdate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> NutritionLog:
    log = await get_nutrition_or_404(session, log_id, current_user.id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(log, field, value)
    await commit_unique_date(session, "a nutrition log already exists for this date")
    await session.refresh(log)
    return log


@router.delete("/nutrition/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_nutrition_log(
    log_id: UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> Response:
    log = await get_nutrition_or_404(session, log_id, current_user.id)
    await session.delete(log)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/summary", response_model=HealthSummary)
async def get_health_summary(
    session: SessionDep,
    current_user: CurrentUserDep,
    start_date: date | None = None,
    end_date: date | None = None,
) -> HealthSummary:
    validate_date_range(start_date, end_date)

    weight_filters = [WeightEntry.user_id == current_user.id]
    nutrition_statement = select(
        func.count(NutritionLog.id),
        func.sum(NutritionLog.calories),
        func.avg(NutritionLog.calories),
        func.avg(NutritionLog.calorie_target),
    ).where(NutritionLog.user_id == current_user.id)
    if start_date is not None:
        weight_filters.append(WeightEntry.recorded_on >= start_date)
        nutrition_statement = nutrition_statement.where(
            NutritionLog.recorded_on >= start_date
        )
    if end_date is not None:
        weight_filters.append(WeightEntry.recorded_on <= end_date)
        nutrition_statement = nutrition_statement.where(
            NutritionLog.recorded_on <= end_date
        )

    weights_statement = select(WeightEntry.recorded_on, WeightEntry.weight_kg).where(
        *weight_filters
    )
    earliest_weight = (
        await session.execute(
            weights_statement.order_by(WeightEntry.recorded_on).limit(1)
        )
    ).one_or_none()
    latest_weight = (
        await session.execute(
            weights_statement.order_by(WeightEntry.recorded_on.desc()).limit(1)
        )
    ).one_or_none()
    nutrition = (await session.execute(nutrition_statement)).one()
    weight_change = (
        latest_weight[1] - earliest_weight[1]
        if latest_weight is not None
        and earliest_weight is not None
        and latest_weight[0] != earliest_weight[0]
        else None
    )
    return HealthSummary(
        start_date=start_date,
        end_date=end_date,
        latest_weight_kg=latest_weight[1] if latest_weight is not None else None,
        weight_change_kg=weight_change,
        nutrition_days_logged=nutrition[0],
        total_calories=nutrition[1] or 0,
        average_daily_calories=(
            Decimal(str(nutrition[2])).quantize(Decimal("0.01"))
            if nutrition[2] is not None
            else None
        ),
        average_calorie_target=(
            Decimal(str(nutrition[3])).quantize(Decimal("0.01"))
            if nutrition[3] is not None
            else None
        ),
    )
