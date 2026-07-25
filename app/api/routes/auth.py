from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import CurrentUserDep, SessionDep, authentication_error
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import (
    AccessTokenResponse,
    UserLogin,
    UserRegistration,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["authentication"])
EMAIL_ALREADY_REGISTERED = "A user with this email already exists"


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_user(
    payload: UserRegistration,
    session: SessionDep,
) -> User:
    hashed_password = await run_in_threadpool(hash_password, payload.password)
    user = User(email=str(payload.email), hashed_password=hashed_password)
    session.add(user)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=EMAIL_ALREADY_REGISTERED,
        ) from exc

    await session.refresh(user)
    return user


@router.post("/login", response_model=AccessTokenResponse)
async def login(
    payload: UserLogin,
    session: SessionDep,
) -> AccessTokenResponse:
    user = await session.scalar(select(User).where(User.email == str(payload.email)))
    stored_hash = user.hashed_password if user is not None else DUMMY_PASSWORD_HASH
    password_matches = await run_in_threadpool(
        verify_password,
        payload.password,
        stored_hash,
    )
    if not password_matches or user is None or not user.is_active:
        raise authentication_error()

    access_token, expires_in = create_access_token(user.id)
    return AccessTokenResponse(
        access_token=access_token,
        expires_in=expires_in,
    )


@router.get("/me", response_model=UserResponse)
async def get_authenticated_user(current_user: CurrentUserDep) -> User:
    return current_user
