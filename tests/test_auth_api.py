from collections.abc import AsyncGenerator, Callable
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import auth as auth_routes
from app.core.config import settings
from app.core.security import verify_password
from app.models.user import User
from app.schemas.auth import GoogleUserInfo

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
    assert set(body) == {
        "id",
        "email",
        "is_active",
        "locale",
        "created_at",
        "updated_at",
    }
    assert body["is_active"] is True
    assert body["locale"] == "uk"
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

    updated = await unauthenticated_api_client.patch(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token_body['access_token']}"},
        json={"locale": "en"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["locale"] == "en"

    invalid_locale = await unauthenticated_api_client.patch(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token_body['access_token']}"},
        json={"locale": "fr"},
    )
    assert invalid_locale.status_code == 422


async def test_google_oauth_creates_and_reuses_account(
    unauthenticated_api_client: AsyncClient,
    sqlite_session_override: SessionOverride,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "google_oauth_client_id", "google-client-id")
    monkeypatch.setattr(
        settings,
        "google_oauth_client_secret",
        SecretStr("google-client-secret"),
    )
    redirect_uri = "http://localhost:43127/api/auth/google"
    state = "s" * 32
    code_challenge = "c" * 43
    authorization = await unauthenticated_api_client.get(
        "/api/v1/auth/google/authorize",
        params={
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
        },
    )
    assert authorization.status_code == 200, authorization.text
    authorization_url = urlparse(authorization.json()["authorization_url"])
    parameters = parse_qs(authorization_url.query)
    assert authorization_url.netloc == "accounts.google.com"
    assert parameters["client_id"] == ["google-client-id"]
    assert parameters["redirect_uri"] == [redirect_uri]
    assert parameters["scope"] == ["openid email"]
    assert parameters["state"] == [state]
    assert parameters["code_challenge"] == [code_challenge]
    assert parameters["code_challenge_method"] == ["S256"]

    async def fake_user_info(_: object) -> GoogleUserInfo:
        return GoogleUserInfo(
            sub="google-user-123",
            email="person@gmail.com",
            email_verified=True,
        )

    monkeypatch.setattr(auth_routes, "fetch_google_user_info", fake_user_info)
    exchange_payload = {
        "code": "authorization-code",
        "redirect_uri": redirect_uri,
        "code_verifier": "v" * 43,
    }
    first = await unauthenticated_api_client.post(
        "/api/v1/auth/google/exchange",
        json=exchange_payload,
    )
    second = await unauthenticated_api_client.post(
        "/api/v1/auth/google/exchange",
        json=exchange_payload,
    )
    assert first.status_code == second.status_code == 200

    first_profile = await unauthenticated_api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {first.json()['access_token']}"},
    )
    second_profile = await unauthenticated_api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {second.json()['access_token']}"},
    )
    assert first_profile.json()["id"] == second_profile.json()["id"]
    assert first_profile.json()["email"] == "person@gmail.com"

    session_iterator = sqlite_session_override()
    session = await anext(session_iterator)
    try:
        users = list((await session.scalars(select(User))).all())
        assert len(users) == 1
        assert users[0].google_subject == "google-user-123"
    finally:
        await session_iterator.aclose()


async def test_google_oauth_does_not_auto_link_third_party_email(
    unauthenticated_api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registration = await unauthenticated_api_client.post(
        "/api/v1/auth/register",
        json={"email": "person@example.com", "password": VALID_PASSWORD},
    )
    assert registration.status_code == 201

    async def fake_user_info(_: object) -> GoogleUserInfo:
        return GoogleUserInfo(
            sub="different-google-user",
            email="person@example.com",
            email_verified=True,
        )

    monkeypatch.setattr(auth_routes, "fetch_google_user_info", fake_user_info)
    response = await unauthenticated_api_client.post(
        "/api/v1/auth/google/exchange",
        json={
            "code": "authorization-code",
            "redirect_uri": "http://localhost:43127/api/auth/google",
            "code_verifier": "v" * 43,
        },
    )
    assert response.status_code == 409
    assert response.json() == {
        "detail": (
            "An account already exists for this email. Sign in with your password."
        )
    }


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
