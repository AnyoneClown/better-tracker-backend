from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.dependencies import CurrentUserDep, SessionDep
from app.cache import cache_response
from app.models.workout import WorkoutRoutine, WorkoutRoutineExercise
from app.schemas.workout import (
    WorkoutRoutineCreate,
    WorkoutRoutineRead,
    WorkoutRoutineUpdate,
)

router = APIRouter(prefix="/workout-routines", tags=["workout routines"])


async def _get_routine(
    routine_id: UUID, session: SessionDep, user_id: UUID
) -> WorkoutRoutine:
    routine = await session.scalar(
        select(WorkoutRoutine)
        .where(
            WorkoutRoutine.id == routine_id,
            WorkoutRoutine.user_id == user_id,
        )
        .options(selectinload(WorkoutRoutine.exercises))
    )
    if routine is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workout routine not found")
    return routine


def _exercise_models(
    payload: WorkoutRoutineCreate | WorkoutRoutineUpdate,
) -> list[WorkoutRoutineExercise]:
    return [
        WorkoutRoutineExercise(
            **item.model_dump(exclude={"position"}), position=position
        )
        for position, item in enumerate(payload.exercises, 1)
    ]


@router.get("", response_model=list[WorkoutRoutineRead])
@cache_response
async def list_routines(
    session: SessionDep, current_user: CurrentUserDep
) -> list[WorkoutRoutine]:
    result = await session.scalars(
        select(WorkoutRoutine)
        .where(WorkoutRoutine.user_id == current_user.id)
        .options(selectinload(WorkoutRoutine.exercises))
        .order_by(WorkoutRoutine.created_at, WorkoutRoutine.id)
    )
    return list(result.all())


@router.post("", response_model=WorkoutRoutineRead, status_code=status.HTTP_201_CREATED)
async def create_routine(
    payload: WorkoutRoutineCreate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> WorkoutRoutine:
    routine = WorkoutRoutine(
        **payload.model_dump(exclude={"exercises"}),
        user_id=current_user.id,
        exercises=_exercise_models(payload),
    )
    session.add(routine)
    await session.flush()
    routine_id = routine.id
    await session.commit()
    return await _get_routine(routine_id, session, current_user.id)


@router.get("/{routine_id}", response_model=WorkoutRoutineRead)
@cache_response
async def get_routine(
    routine_id: UUID, session: SessionDep, current_user: CurrentUserDep
) -> WorkoutRoutine:
    return await _get_routine(routine_id, session, current_user.id)


@router.patch("/{routine_id}", response_model=WorkoutRoutineRead)
async def update_routine(
    routine_id: UUID,
    payload: WorkoutRoutineUpdate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> WorkoutRoutine:
    routine = await _get_routine(routine_id, session, current_user.id)
    for field_name, value in payload.model_dump(
        exclude_unset=True, exclude={"exercises"}
    ).items():
        setattr(routine, field_name, value)
    if "exercises" in payload.model_fields_set:
        routine.replace_exercises([])
        await session.flush()
        routine.replace_exercises(_exercise_models(payload))
    routine.updated_at = datetime.now(UTC)
    await session.commit()
    return await _get_routine(routine_id, session, current_user.id)


@router.delete(
    "/{routine_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_routine(
    routine_id: UUID, session: SessionDep, current_user: CurrentUserDep
) -> Response:
    routine = await _get_routine(routine_id, session, current_user.id)
    await session.delete(routine)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
