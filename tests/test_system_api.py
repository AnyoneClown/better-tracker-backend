from collections.abc import AsyncIterator
from typing import Any

from httpx import AsyncClient
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import get_session
from app.main import app


async def test_root_liveness_and_readiness(api_client: AsyncClient) -> None:
    root = await api_client.get("/")
    assert root.status_code == 200
    assert root.json()["docs"] == "/docs"

    liveness = await api_client.get("/healthz")
    assert liveness.status_code == 200
    assert liveness.json() == {"message": "ok"}

    readiness = await api_client.get("/readyz")
    assert readiness.status_code == 200
    assert readiness.json() == {"message": "ready"}


async def test_readiness_reports_database_failure(api_client: AsyncClient) -> None:
    class UnavailableSession:
        async def execute(self, *_: Any, **__: Any) -> None:
            raise SQLAlchemyError("database offline")

    async def unavailable_session() -> AsyncIterator[UnavailableSession]:
        yield UnavailableSession()

    sqlite_override = app.dependency_overrides[get_session]
    app.dependency_overrides[get_session] = unavailable_session
    try:
        response = await api_client.get("/readyz")
    finally:
        app.dependency_overrides[get_session] = sqlite_override

    assert response.status_code == 503
    assert response.json() == {"detail": "database is unavailable"}
