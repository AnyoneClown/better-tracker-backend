from collections.abc import AsyncGenerator, Callable
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_password
from app.models.user import User

VALID_PASSWORD = "StrongPassword1!"
SessionOverride = Callable[[], AsyncGenerator[AsyncSession]]


async def test_user_can_register_with_normalized_email(
    unauthenticated_api_client: AsyncClient,
    sqlite_session_override: SessionOverride,
) -> None:
    response = await unauthenticated_api_client.post(
        "/api/v1/auth/register",
        json={
            "email": "  New.User@Example.COM ",
            "password": VALID_PASSWORD,
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == "new.user@example.com"
    assert set(body) == {"id", "email", "is_active", "created_at", "updated_at"}
    assert body["is_active"] is True
    UUID(body["id"])

    session_iterator = sqlite_session_override()
    session = await anext(session_iterator)
    try:
        user = await session.scalar(
            select(User).where(User.email == "new.user@example.com")
        )
        assert user is not None
        assert user.hashed_password != VALID_PASSWORD
        assert user.hashed_password.startswith("$argon2id$")
        assert verify_password(VALID_PASSWORD, user.hashed_password)
        assert not verify_password("WrongPassword1!", user.hashed_password)
    finally:
        await session_iterator.aclose()


async def test_registration_rejects_duplicate_email_case_insensitively(
    unauthenticated_api_client: AsyncClient,
) -> None:
    first_response = await unauthenticated_api_client.post(
        "/api/v1/auth/register",
        json={"email": "Person@Example.com", "password": VALID_PASSWORD},
    )
    duplicate_response = await unauthenticated_api_client.post(
        "/api/v1/auth/register",
        json={"email": "person@example.COM", "password": VALID_PASSWORD},
    )

    assert first_response.status_code == 201, first_response.text
    assert duplicate_response.status_code == 409
    assert duplicate_response.json() == {
        "detail": "A user with this email already exists"
    }


@pytest.mark.parametrize(
    "email",
    [
        "not-an-email",
        "user@-example.com",
        "user..name@example.com",
    ],
)
async def test_registration_rejects_invalid_email(
    unauthenticated_api_client: AsyncClient,
    email: str,
) -> None:
    response = await unauthenticated_api_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": VALID_PASSWORD},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "password",
    [
        "Short1!",
        "alllowercase1!",
        "ALLUPPERCASE1!",
        "MissingNumber!",
        "MissingSpecial1",
        "WhitespaceOnly1 ",
        "A" * 126 + "a1!",
    ],
)
async def test_registration_rejects_weak_password(
    unauthenticated_api_client: AsyncClient,
    password: str,
) -> None:
    response = await unauthenticated_api_client.post(
        "/api/v1/auth/register",
        json={"email": "valid@example.com", "password": password},
    )

    assert response.status_code == 422


async def test_registration_rejects_unknown_fields(
    unauthenticated_api_client: AsyncClient,
) -> None:
    response = await unauthenticated_api_client.post(
        "/api/v1/auth/register",
        json={
            "email": "valid@example.com",
            "password": VALID_PASSWORD,
            "is_admin": True,
        },
    )

    assert response.status_code == 422


async def test_user_can_login_and_get_current_profile(
    unauthenticated_api_client: AsyncClient,
) -> None:
    registration = await unauthenticated_api_client.post(
        "/api/v1/auth/register",
        json={"email": " Login.User@Example.COM ", "password": VALID_PASSWORD},
    )
    login = await unauthenticated_api_client.post(
        "/api/v1/auth/login",
        json={"email": "login.user@example.com", "password": VALID_PASSWORD},
    )

    assert registration.status_code == 201, registration.text
    assert login.status_code == 200, login.text
    token_body = login.json()
    assert token_body["token_type"] == "bearer"
    assert token_body["expires_in"] == 1800
    assert token_body["access_token"]

    profile = await unauthenticated_api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token_body['access_token']}"},
    )
    assert profile.status_code == 200, profile.text
    assert profile.json()["id"] == registration.json()["id"]
    assert profile.json()["email"] == "login.user@example.com"


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("missing@example.com", VALID_PASSWORD),
        ("login.user@example.com", "WrongPassword1!"),
    ],
)
async def test_login_rejects_invalid_credentials_without_user_enumeration(
    unauthenticated_api_client: AsyncClient,
    email: str,
    password: str,
) -> None:
    await unauthenticated_api_client.post(
        "/api/v1/auth/register",
        json={"email": "login.user@example.com", "password": VALID_PASSWORD},
    )

    response = await unauthenticated_api_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}
    assert response.headers["www-authenticate"] == "Bearer"


async def test_protected_endpoints_require_a_valid_bearer_token(
    unauthenticated_api_client: AsyncClient,
) -> None:
    missing = await unauthenticated_api_client.get("/api/v1/workouts")
    invalid = await unauthenticated_api_client.get(
        "/api/v1/workouts",
        headers={"Authorization": "Bearer not-a-valid-token"},
    )

    assert missing.status_code == invalid.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert invalid.json() == {"detail": "Could not validate credentials"}


async def test_inactive_user_cannot_login_or_use_an_existing_token(
    unauthenticated_api_client: AsyncClient,
    sqlite_session_override: SessionOverride,
) -> None:
    registration = await unauthenticated_api_client.post(
        "/api/v1/auth/register",
        json={"email": "inactive@example.com", "password": VALID_PASSWORD},
    )
    login = await unauthenticated_api_client.post(
        "/api/v1/auth/login",
        json={"email": "inactive@example.com", "password": VALID_PASSWORD},
    )
    assert registration.status_code == 201
    assert login.status_code == 200

    session_iterator = sqlite_session_override()
    session = await anext(session_iterator)
    try:
        user = await session.scalar(
            select(User).where(User.email == "inactive@example.com")
        )
        assert user is not None
        user.is_active = False
        await session.commit()
    finally:
        await session_iterator.aclose()

    rejected_login = await unauthenticated_api_client.post(
        "/api/v1/auth/login",
        json={"email": "inactive@example.com", "password": VALID_PASSWORD},
    )
    rejected_token = await unauthenticated_api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert rejected_login.status_code == rejected_token.status_code == 401
