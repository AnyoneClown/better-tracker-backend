from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

from app import cache
from app.api.dependencies import get_current_user
from app.core.security import create_access_token
from app.models.user import User
from app.schemas.auth import UserResponse


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int | None] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        self.expirations[key] = ex
        return True

    async def delete(self, key: str) -> int:
        existed = key in self.values
        self.values.pop(key, None)
        self.expirations.pop(key, None)
        return int(existed)


async def test_cached_response_is_user_scoped_and_invalidated(monkeypatch) -> None:
    redis = FakeRedis()
    monkeypatch.setattr(cache, "_client", redis)
    calls = 0

    @cache.cache_response
    async def load(value: int, session: object, current_user: object) -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"value": value, "calls": calls}

    owner = SimpleNamespace(id=uuid4())
    other = SimpleNamespace(id=uuid4())

    assert await load(1, object(), owner) == {"value": 1, "calls": 1}
    assert await load(1, object(), owner) == {"value": 1, "calls": 1}
    assert await load(1, object(), other) == {"value": 1, "calls": 2}

    await cache.invalidate_user_cache(owner.id)

    assert await load(1, object(), owner) == {"value": 1, "calls": 3}


async def test_auth_user_cache_avoids_db_and_rejects_bad_entries(monkeypatch) -> None:
    redis = FakeRedis()
    monkeypatch.setattr(cache, "_client", redis)
    now = datetime.now(UTC)
    user = User(
        id=uuid4(),
        email="owner@example.com",
        hashed_password="must-not-be-cached",
        locale="uk",
        is_active=True,
        created_at=now,
        updated_at=now,
    )

    class Session:
        calls = 0

        async def scalar(self, _: object) -> User:
            self.calls += 1
            return user

    session = Session()
    token, _ = create_access_token(user.id)
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=token,
    )

    async def authenticate() -> UserResponse:
        return await get_current_user(
            Request({"type": "http"}),  # type: ignore[arg-type]
            session,  # type: ignore[arg-type]
            credentials,
        )

    assert (await authenticate()).id == user.id
    assert (await authenticate()).id == user.id
    assert session.calls == 1

    key = f"{cache.AUTH_USER_PREFIX}:{user.id}"
    assert redis.expirations[key] == cache.AUTH_USER_TTL_SECONDS == 30
    assert "hashed_password" not in redis.values[key]

    cached = UserResponse.model_validate(user)
    bad_entries = (
        "not-json",
        cached.model_copy(update={"id": uuid4()}).model_dump_json(),
        cached.model_copy(update={"is_active": False}).model_dump_json(),
    )
    for expected_calls, bad_entry in enumerate(bad_entries, start=2):
        redis.values[key] = bad_entry
        assert (await authenticate()).id == user.id
        assert session.calls == expected_calls

    await cache.invalidate_auth_user_cache(user.id)
    assert (await authenticate()).id == user.id
    assert session.calls == 5
