from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import SessionDep
from app.schemas.common import MessageResponse

router = APIRouter(tags=["system"])


@router.get("/healthz", response_model=MessageResponse)
async def liveness() -> MessageResponse:
    return MessageResponse(message="ok")


@router.get("/readyz", response_model=MessageResponse)
async def readiness(session: SessionDep) -> MessageResponse:
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database is unavailable",
        ) from exc
    return MessageResponse(message="ready")
