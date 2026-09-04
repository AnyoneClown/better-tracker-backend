from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import RequestResponseEndpoint

from app.api.router import api_router
from app.cache import close_cache, initialize_cache, invalidate_user_cache
from app.core.config import settings
from app.db.session import async_session_factory, engine
from app.integrations.monobank.service import (
    cancel_all_monobank_syncs,
    mark_interrupted_monobank_syncs,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await initialize_cache()
    await mark_interrupted_monobank_syncs(async_session_factory)
    try:
        yield
    finally:
        await cancel_all_monobank_syncs()
        await close_cache()
        await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "Authenticated API for workouts, cash flow and budgets, wealth, "
        "body weight, and daily nutrition."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def invalidate_cache_after_mutation(
    request: Request,
    call_next: RequestResponseEndpoint,
) -> Response:
    response = await call_next(request)
    user_id = getattr(request.state, "user_id", None)
    if request.method not in {"GET", "HEAD", "OPTIONS"} and response.status_code < 400:
        if user_id is not None:
            await invalidate_user_cache(user_id)
    return response

app.include_router(api_router)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "docs": "/docs",
        "health": "/healthz",
        "readiness": "/readyz",
    }
