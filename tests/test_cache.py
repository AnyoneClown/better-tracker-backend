from types import SimpleNamespace
from uuid import uuid4

from app import cache


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

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
        return True

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
