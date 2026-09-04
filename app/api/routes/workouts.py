from datetime import UTC, datetime
from decimal import Decimal
from math import ceil
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.api.dependencies import CurrentUserDep, SessionDep
from app.cache import cache_response
from app.models.workout import Workout, WorkoutSet
from app.schemas.workout import (
    ActiveWorkoutCreate,
    WorkoutCreate,
    WorkoutExerciseSummary,
    WorkoutListResponse,
    WorkoutRead,
    WorkoutSummary,
    WorkoutUpdate,
)

router = APIRouter(prefix="/workouts", tags=["workouts"])


async def _get_workout(
    workout_id: UUID,
    session: SessionDep,
    user_id: UUID,
) -> Workout:
    result = await session.execute(
        select(Workout)
        .where(Workout.id == workout_id, Workout.user_id == user_id)
        .options(selectinload(Workout.sets))
    )
    workout = result.scalar_one_or_none()
    if workout is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workout not found",
        )
    return workout


def _validate_date_range(date_from: datetime | None, date_to: datetime | None) -> None:
    for field_name, value in (("date_from", date_from), ("date_to", date_to)):
        if value is not None and value.utcoffset() is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{field_name} must include a timezone offset",
            )
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="date_from must be earlier than or equal to date_to",
        )


def _set_models(
    payload: WorkoutCreate | WorkoutUpdate | ActiveWorkoutCreate,
) -> list[WorkoutSet]:
    return [
        WorkoutSet(**item.model_dump(exclude={"position"}), position=position)
        for position, item in enumerate(payload.sets, 1)
    ]


def _reject_unchecked_completed_sets(payload: WorkoutCreate | WorkoutUpdate) -> None:
    if any(not item.is_completed for item in payload.sets):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Unchecked sets are only allowed on an active workout",
        )


@router.post(
    "",
    response_model=WorkoutRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_workout(
    payload: WorkoutCreate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> Workout:
    _reject_unchecked_completed_sets(payload)
    workout = Workout(
        **payload.model_dump(exclude={"sets"}),
        user_id=current_user.id,
        completed_at=datetime.now(UTC),
        sets=_set_models(payload),
    )
    session.add(workout)
    await session.flush()
    workout_id = workout.id
    await session.commit()
    return await _get_workout(workout_id, session, current_user.id)


@router.get("/active", response_model=WorkoutRead | None)
async def get_active_workout(
    session: SessionDep,
    current_user: CurrentUserDep,
) -> Workout | None:
    result = await session.execute(
        select(Workout)
        .where(
            Workout.user_id == current_user.id,
            Workout.completed_at.is_(None),
        )
        .options(selectinload(Workout.sets))
    )
    return result.scalar_one_or_none()


@router.post(
    "/active",
    response_model=WorkoutRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_active_workout(
    payload: ActiveWorkoutCreate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> Workout:
    existing = await session.scalar(
        select(Workout.id).where(
            Workout.user_id == current_user.id,
            Workout.completed_at.is_(None),
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active workout already exists",
        )
    workout = Workout(
        **payload.model_dump(exclude={"sets"}),
        user_id=current_user.id,
        completed_at=None,
        sets=_set_models(payload),
    )
    session.add(workout)
    try:
        await session.flush()
        workout_id = workout.id
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active workout already exists",
        ) from exc
    return await _get_workout(workout_id, session, current_user.id)


@router.get("", response_model=WorkoutListResponse)
@cache_response
async def list_workouts(
    session: SessionDep,
    current_user: CurrentUserDep,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> WorkoutListResponse:
    _validate_date_range(date_from, date_to)

    filters = [
        Workout.user_id == current_user.id,
        Workout.completed_at.is_not(None),
    ]
    if date_from is not None:
        filters.append(Workout.performed_at >= date_from)
    if date_to is not None:
        filters.append(Workout.performed_at <= date_to)

    total = await session.scalar(
        select(func.count()).select_from(Workout).where(*filters)
    )
    result = await session.execute(
        select(Workout)
        .where(*filters)
        .options(selectinload(Workout.sets))
        .order_by(Workout.performed_at.desc(), Workout.id.desc())
        .offset(offset)
        .limit(limit)
    )
    workouts = list(result.scalars().all())
    return WorkoutListResponse(
        items=[WorkoutRead.model_validate(workout) for workout in workouts],
        total=total or 0,
        offset=offset,
        limit=limit,
    )


@router.get("/summary", response_model=WorkoutSummary)
@cache_response
async def get_workout_summary(
    session: SessionDep,
    current_user: CurrentUserDep,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
) -> WorkoutSummary:
    _validate_date_range(date_from, date_to)

    filters = [
        Workout.user_id == current_user.id,
        Workout.completed_at.is_not(None),
    ]
    if date_from is not None:
        filters.append(Workout.performed_at >= date_from)
    if date_to is not None:
        filters.append(Workout.performed_at <= date_to)

    workout_totals = (
        await session.execute(
            select(
                func.count(Workout.id),
                func.sum(Workout.duration_minutes),
                func.avg(Workout.duration_minutes),
            ).where(*filters)
        )
    ).one()
    exercise_rows = (
        await session.execute(
            select(
                WorkoutSet.exercise,
                func.count(WorkoutSet.id),
                func.sum(WorkoutSet.reps),
                func.sum(WorkoutSet.weight_kg * WorkoutSet.reps),
                func.sum(WorkoutSet.distance_km),
                func.sum(WorkoutSet.duration_seconds),
            )
            .join(Workout, Workout.id == WorkoutSet.workout_id)
            .where(*filters)
            .group_by(WorkoutSet.exercise)
            .order_by(WorkoutSet.exercise)
        )
    ).all()

    exercises = [
        WorkoutExerciseSummary(
            exercise=exercise,
            sets=set_count,
            total_reps=total_reps or 0,
            volume_kg=Decimal(str(volume_kg or 0)),
            distance_km=Decimal(str(distance_km or 0)),
            duration_seconds=duration_seconds or 0,
        )
        for (
            exercise,
            set_count,
            total_reps,
            volume_kg,
            distance_km,
            duration_seconds,
        ) in exercise_rows
    ]
    zero = Decimal("0")
    average_duration = workout_totals[2]
    return WorkoutSummary(
        date_from=date_from,
        date_to=date_to,
        workout_count=workout_totals[0],
        total_duration_minutes=workout_totals[1] or 0,
        average_duration_minutes=(
            Decimal(str(average_duration)).quantize(Decimal("0.01"))
            if average_duration is not None
            else None
        ),
        total_sets=sum((exercise.sets for exercise in exercises), 0),
        total_reps=sum((exercise.total_reps for exercise in exercises), 0),
        total_volume_kg=sum(
            (exercise.volume_kg for exercise in exercises),
            zero,
        ),
        total_distance_km=sum(
            (exercise.distance_km for exercise in exercises),
            zero,
        ),
        total_set_duration_seconds=sum(
            (exercise.duration_seconds for exercise in exercises),
            0,
        ),
        exercises=exercises,
    )


@router.get("/{workout_id}", response_model=WorkoutRead)
@cache_response
async def get_workout(
    workout_id: UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> Workout:
    return await _get_workout(workout_id, session, current_user.id)


@router.post("/{workout_id}/complete", response_model=WorkoutRead)
async def complete_workout(
    workout_id: UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> Workout:
    workout = await _get_workout(workout_id, session, current_user.id)
    if workout.completed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Workout is already complete",
        )

    retained = [item for item in workout.sets if item.is_completed]
    workout.replace_sets(retained)
    await session.flush()
    counts: dict[str, int] = {}
    for position, item in enumerate(retained, 1):
        counts[item.exercise] = counts.get(item.exercise, 0) + 1
        item.position = position
        item.set_number = counts[item.exercise]

    completed_at = datetime.now(UTC)
    performed_at = workout.performed_at
    if performed_at.tzinfo is None:
        performed_at = performed_at.replace(tzinfo=UTC)
    workout.duration_minutes = max(
        1, ceil((completed_at - performed_at.astimezone(UTC)).total_seconds() / 60)
    )
    workout.completed_at = completed_at
    workout.rest_timer_ends_at = None
    await session.commit()
    return await _get_workout(workout_id, session, current_user.id)


@router.patch("/{workout_id}", response_model=WorkoutRead)
async def update_workout(
    workout_id: UUID,
    payload: WorkoutUpdate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> Workout:
    workout = await _get_workout(workout_id, session, current_user.id)

    if workout.completed_at is not None:
        _reject_unchecked_completed_sets(payload)
        if payload.rest_timer_ends_at is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Completed workouts cannot have a rest timer",
            )

    for field_name, value in payload.model_dump(
        exclude_unset=True, exclude={"sets"}
    ).items():
        setattr(workout, field_name, value)

    if "sets" in payload.model_fields_set:
        replacement_sets = _set_models(payload)
        workout.replace_sets([])
        await session.flush()
        workout.replace_sets(replacement_sets)
        workout.updated_at = datetime.now(UTC)

    await session.commit()
    return await _get_workout(workout_id, session, current_user.id)


@router.delete(
    "/{workout_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_workout(
    workout_id: UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> Response:
    workout = await _get_workout(workout_id, session, current_user.id)
    await session.delete(workout)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
