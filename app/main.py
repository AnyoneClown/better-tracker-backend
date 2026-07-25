from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.db.session import async_session_factory, engine
from app.integrations.monobank.service import (
    cancel_all_monobank_syncs,
    mark_interrupted_monobank_syncs,
)
from app.integrations.privatbank.service import (
    cancel_all_privatbank_syncs,
    mark_interrupted_privatbank_syncs,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await mark_interrupted_monobank_syncs(async_session_factory)
    await mark_interrupted_privatbank_syncs(async_session_factory)
    try:
        yield
    finally:
        await cancel_all_monobank_syncs()
        await cancel_all_privatbank_syncs()
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

app.include_router(api_router)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "docs": "/docs",
        "health": "/healthz",
        "readiness": "/readyz",
    }
