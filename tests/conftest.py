from collections.abc import AsyncGenerator, AsyncIterator, Callable
from datetime import UTC
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import app.models  # noqa: F401 -- register every table before create_all
from app.db.base import Base
from app.db.session import get_session
from app.main import app
from app.models.workout import Workout

SessionOverride = Callable[[], AsyncGenerator[AsyncSession]]
TEST_USER_EMAIL = "owner@example.com"
TEST_USER_PASSWORD = "OwnerPassword1!"


@pytest.fixture
async def sqlite_session_override(tmp_path: Path) -> AsyncIterator[SessionOverride]:
    database_path = tmp_path / "better-tracker-test.sqlite3"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection: Any, _: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    def restore_workout_timezone(workout: Workout, _: Any) -> None:
        # SQLite drops timezone offsets from DateTime values. Production
        # CockroachDB does not, so restore UTC after ORM loads in this test DB.
        if workout.performed_at.tzinfo is None:
            workout.performed_at = workout.performed_at.replace(tzinfo=UTC)

    event.listen(Workout, "load", restore_workout_timezone)

    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        autoflush=False,
        expire_on_commit=False,
    )

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def override_get_session() -> AsyncGenerator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    try:
        yield override_get_session
    finally:
        event.remove(Workout, "load", restore_workout_timezone)
        await engine.dispose()


@pytest.fixture
async def unauthenticated_api_client(
    sqlite_session_override: SessionOverride,
) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_session] = sqlite_session_override
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.fixture
async def api_client(
    unauthenticated_api_client: AsyncClient,
) -> AsyncIterator[AsyncClient]:
    registration = await unauthenticated_api_client.post(
        "/api/v1/auth/register",
        json={"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD},
    )
    assert registration.status_code == 201, registration.text
    login = await unauthenticated_api_client.post(
        "/api/v1/auth/login",
        json={"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD},
    )
    assert login.status_code == 200, login.text
    unauthenticated_api_client.headers["Authorization"] = (
        f"Bearer {login.json()['access_token']}"
    )
    yield unauthenticated_api_client
