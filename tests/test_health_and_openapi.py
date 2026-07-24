from httpx import ASGITransport, AsyncClient

from app.main import app


async def test_liveness() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"message": "ok"}


def test_openapi_exposes_each_tracker_domain() -> None:
    paths = app.openapi()["paths"]

    expected_paths = {
        "/api/v1/workouts",
        "/api/v1/finance/transactions",
        "/api/v1/finance/budgets",
        "/api/v1/finance/summary",
        "/api/v1/wealth/accounts",
        "/api/v1/wealth/savings-goals",
        "/api/v1/wealth/net-worth-snapshots/capture",
        "/api/v1/health/weights",
        "/api/v1/health/nutrition",
        "/api/v1/health/summary",
    }

    assert expected_paths <= set(paths)
