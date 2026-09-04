from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import get_cached_auth_user, store_auth_user
from app.core.security import decode_access_token
from app.db.session import get_session
from app.models.user import User
from app.schemas.auth import UserResponse

SessionDep = Annotated[AsyncSession, Depends(get_session)]
bearer_scheme = HTTPBearer(
    auto_error=False,
    description="Access token returned by POST /api/v1/auth/login",
)


def authentication_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    request: Request,
    session: SessionDep,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
) -> UserResponse:
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise authentication_error()
    try:
        user_id = decode_access_token(credentials.credentials)
    except jwt.InvalidTokenError as exc:
        raise authentication_error() from exc

    user = await get_cached_auth_user(user_id)
    if user is None:
        database_user = await session.scalar(
            select(User).where(User.id == user_id, User.is_active.is_(True))
        )
        if database_user is None:
            raise authentication_error()
        user = UserResponse.model_validate(database_user)
        await store_auth_user(user)
    request.state.user_id = user.id
    return user


CurrentUserDep = Annotated[UserResponse, Depends(get_current_user)]
