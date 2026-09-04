import hashlib
import json
from collections.abc import Awaitable, Callable
from functools import wraps
from inspect import signature
from typing import cast
from uuid import UUID, uuid4

from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.schemas.auth import UserResponse

PREFIX = "better-tracker:response-cache:v1"
AUTH_USER_PREFIX = "better-tracker:auth-user:v1"
AUTH_USER_TTL_SECONDS = settings.access_token_expire_minutes * 60

_client = (
    Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
    )
    if settings.redis_url
    else None
)


async def initialize_cache() -> None:
    if _client is not None:
        await _replace_generation(f"{PREFIX}:generation")


async def close_cache() -> None:
    if _client is not None:
        await _client.aclose()


async def invalidate_user_cache(user_id: UUID) -> None:
    await _replace_generation(f"{PREFIX}:user:{user_id}:generation")


async def get_cached_auth_user(user_id: UUID) -> UserResponse | None:
    if _client is None:
        return None
    try:
        cached = _text(await _client.get(f"{AUTH_USER_PREFIX}:{user_id}"))
        if cached is None:
            return None
        user = UserResponse.model_validate_json(cached)
        return user if user.id == user_id and user.is_active else None
    except (RedisError, RuntimeError, ValidationError, ValueError):
        return None


async def store_auth_user(user: UserResponse) -> None:
    if _client is None:
        return
    try:
        await _client.set(
            f"{AUTH_USER_PREFIX}:{user.id}",
            user.model_dump_json(),
            ex=AUTH_USER_TTL_SECONDS,
        )
    except (RedisError, RuntimeError, TypeError, ValueError):
        pass


async def invalidate_auth_user_cache(user_id: UUID) -> None:
    if _client is None:
        return
    try:
        await _client.delete(f"{AUTH_USER_PREFIX}:{user_id}")
    except (RedisError, RuntimeError):
        pass


async def _replace_generation(key: str) -> None:
    if _client is None:
        return
    try:
        await _client.set(key, uuid4().hex)
    except (RedisError, RuntimeError):
        pass


def _text(value: bytes | str | None) -> str | None:
    return value.decode() if isinstance(value, bytes) else value


async def _generation(key: str) -> str:
    assert _client is not None
    if (current := _text(await _client.get(key))) is not None:
        return current
    candidate = uuid4().hex
    if await _client.set(key, candidate, nx=True):
        return candidate
    return _text(await _client.get(key)) or candidate


async def _lookup(
    user_id: UUID,
    operation: str,
    arguments: dict[str, object],
) -> tuple[str | None, str | None]:
    if _client is None:
        return None, None
    try:
        global_generation = await _generation(f"{PREFIX}:generation")
        user_generation = await _generation(
            f"{PREFIX}:user:{user_id}:generation"
        )
        payload = json.dumps(
            jsonable_encoder(arguments),
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(f"{operation}:{payload}".encode()).hexdigest()
        key = f"{PREFIX}:{global_generation}:{user_id}:{user_generation}:{digest}"
        return key, _text(await _client.get(key))
    except (RedisError, RuntimeError, TypeError, ValueError):
        return None, None


async def _store(key: str | None, value: object) -> None:
    if _client is None or key is None:
        return
    try:
        await _client.set(
            key,
            json.dumps(jsonable_encoder(value), separators=(",", ":")),
            ex=settings.cache_ttl_seconds,
        )
    except (RedisError, RuntimeError, TypeError, ValueError):
        pass


def cache_response[**P, R](
    function: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    function_signature = signature(function)

    @wraps(function)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        arguments = dict(function_signature.bind(*args, **kwargs).arguments)
        current_user = arguments.pop("current_user", None)
        arguments.pop("session", None)
        user_id = getattr(current_user, "id", None)
        if not isinstance(user_id, UUID):
            return await function(*args, **kwargs)

        key, cached = await _lookup(
            user_id,
            f"{function.__module__}.{function.__qualname__}",
            arguments,
        )
        if cached is not None:
            try:
                return cast(R, json.loads(cached))
            except json.JSONDecodeError:
                pass

        result = await function(*args, **kwargs)
        await _store(key, result)
        return result

    return wrapper
