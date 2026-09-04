import secrets
from typing import Annotated
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import AnyHttpUrl, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import CurrentUserDep, SessionDep, authentication_error
from app.cache import invalidate_auth_user_cache
from app.core.config import settings
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import (
    AccessTokenResponse,
    GoogleAuthorizationResponse,
    GoogleCodeExchange,
    GoogleUserInfo,
    UserLogin,
    UserPreferences,
    UserRegistration,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["authentication"])
EMAIL_ALREADY_REGISTERED = "A user with this email already exists"
GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def google_credentials() -> tuple[str, str]:
    client_id = settings.google_oauth_client_id
    client_secret = settings.google_oauth_client_secret
    if client_id is None or client_secret is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in is not configured",
        )
    return client_id, client_secret.get_secret_value()


async def fetch_google_user_info(payload: GoogleCodeExchange) -> GoogleUserInfo:
    client_id, client_secret = google_credentials()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            token_response = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": payload.code,
                    "code_verifier": payload.code_verifier,
                    "grant_type": "authorization_code",
                    "redirect_uri": str(payload.redirect_uri),
                },
            )
            token_response.raise_for_status()
            token_payload = token_response.json()
            if not isinstance(token_payload, dict):
                raise ValueError("Google returned an invalid token response")
            access_token = token_payload.get("access_token")
            if not isinstance(access_token, str) or not access_token:
                raise ValueError("Google did not return an access token")
            user_response = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            user_response.raise_for_status()
            return GoogleUserInfo.model_validate(user_response.json())
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Google authentication is unavailable",
        ) from exc
    except (httpx.HTTPStatusError, ValidationError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google authentication failed",
        ) from exc


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
        user_id=user.id,
    )


@router.get("/google/authorize", response_model=GoogleAuthorizationResponse)
async def authorize_google(
    redirect_uri: Annotated[AnyHttpUrl, Query()],
    state: Annotated[str, Query(min_length=32, max_length=256)],
    code_challenge: Annotated[
        str,
        Query(min_length=43, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"),
    ],
) -> GoogleAuthorizationResponse:
    client_id, _ = google_credentials()
    authorization_url = f"{GOOGLE_AUTHORIZATION_URL}?{
        urlencode(
            {
                'client_id': client_id,
                'redirect_uri': str(redirect_uri),
                'response_type': 'code',
                'scope': 'openid email',
                'state': state,
                'code_challenge': code_challenge,
                'code_challenge_method': 'S256',
                'prompt': 'select_account',
            }
        )
    }"
    return GoogleAuthorizationResponse(authorization_url=authorization_url)


@router.post("/google/exchange", response_model=AccessTokenResponse)
async def exchange_google_code(
    payload: GoogleCodeExchange,
    session: SessionDep,
) -> AccessTokenResponse:
    profile = await fetch_google_user_info(payload)
    if not profile.email_verified:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google email is not verified",
        )

    user = await session.scalar(select(User).where(User.google_subject == profile.sub))
    if user is None:
        email = str(profile.email)
        user = await session.scalar(select(User).where(User.email == email))
        if user is not None:
            google_controls_email = (
                email.endswith("@gmail.com") or profile.hd is not None
            )
            if user.google_subject is not None or not google_controls_email:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "An account already exists for this email. "
                        "Sign in with your password."
                    ),
                )
            user.google_subject = profile.sub
        else:
            hashed_password = await run_in_threadpool(
                hash_password,
                secrets.token_urlsafe(32),
            )
            user = User(
                email=email,
                hashed_password=hashed_password,
                google_subject=profile.sub,
            )
            session.add(user)

        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            user = await session.scalar(
                select(User).where(User.google_subject == profile.sub)
            )
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This Google account is already linked",
                ) from exc
        await session.refresh(user)

    if not user.is_active:
        raise authentication_error()
    access_token, expires_in = create_access_token(user.id)
    return AccessTokenResponse(
        access_token=access_token,
        expires_in=expires_in,
        user_id=user.id,
    )


@router.get("/me", response_model=UserResponse)
async def get_authenticated_user(current_user: CurrentUserDep) -> UserResponse:
    return current_user


@router.patch("/me", response_model=UserResponse)
async def update_authenticated_user(
    payload: UserPreferences,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> User:
    user = await session.scalar(
        select(User).where(
            User.id == current_user.id,
            User.is_active.is_(True),
        )
    )
    if user is None:
        raise authentication_error()
    user.locale = payload.locale
    await session.commit()
    await session.refresh(user)
    await invalidate_auth_user_cache(user.id)
    return user
