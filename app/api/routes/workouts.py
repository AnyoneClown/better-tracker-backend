from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.dependencies import SessionDep
from app.models.workout import Workout, WorkoutSet
from app.schemas.workout import (
    WorkoutCreate,
    WorkoutListResponse,
    WorkoutRead,
    WorkoutUpdate,
)

router = APIRouter(prefix="/workouts", tags=["workouts"])


async def _get_workout(workout_id: UUID, session: SessionDep) -> Workout:
    result = await session.execute(
        select(Workout)
        .where(Workout.id == workout_id)
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
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{field_name} must include a timezone offset",
            )
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_from must be earlier than or equal to date_to",
        )


@router.post(
    "",
    response_model=WorkoutRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_workout(payload: WorkoutCreate, session: SessionDep) -> Workout:
    workout = Workout(
        **payload.model_dump(exclude={"sets"}),
        sets=[WorkoutSet(**item.model_dump()) for item in payload.sets],
    )
    session.add(workout)
    await session.flush()
    workout_id = workout.id
    await session.commit()
    return await _get_workout(workout_id, session)


@router.get("", response_model=WorkoutListResponse)
async def list_workouts(
    session: SessionDep,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> WorkoutListResponse:
    _validate_date_range(date_from, date_to)

    filters = []
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


@router.get("/{workout_id}", response_model=WorkoutRead)
async def get_workout(workout_id: UUID, session: SessionDep) -> Workout:
    return await _get_workout(workout_id, session)


@router.patch("/{workout_id}", response_model=WorkoutRead)
async def update_workout(
    workout_id: UUID,
    payload: WorkoutUpdate,
    session: SessionDep,
) -> Workout:
    workout = await _get_workout(workout_id, session)

    for field_name, value in payload.model_dump(
        exclude_unset=True, exclude={"sets"}
    ).items():
        setattr(workout, field_name, value)

    if "sets" in payload.model_fields_set:
        replacement_sets = [WorkoutSet(**item.model_dump()) for item in payload.sets]
        workout.replace_sets([])
        await session.flush()
        workout.replace_sets(replacement_sets)
        workout.updated_at = datetime.now(UTC)

    await session.commit()
    return await _get_workout(workout_id, session)


@router.delete(
    "/{workout_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_workout(workout_id: UUID, session: SessionDep) -> Response:
    workout = await _get_workout(workout_id, session)
    await session.delete(workout)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
