from fastapi import APIRouter

from app.api.routes import (
    auth,
    finance,
    health,
    monobank,
    system,
    wealth,
    workouts,
)

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(auth.router, prefix="/api/v1")
api_router.include_router(workouts.router, prefix="/api/v1")
api_router.include_router(finance.router, prefix="/api/v1")
api_router.include_router(monobank.router, prefix="/api/v1")
api_router.include_router(wealth.router, prefix="/api/v1")
api_router.include_router(health.router, prefix="/api/v1")
