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
    schema = app.openapi()
    paths = schema["paths"]

    expected_paths = {
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/google/authorize",
        "/api/v1/auth/google/exchange",
        "/api/v1/auth/me",
        "/api/v1/workouts",
        "/api/v1/workouts/active",
        "/api/v1/workouts/{workout_id}/complete",
        "/api/v1/workout-routines",
        "/api/v1/finance/transactions",
        "/api/v1/finance/budgets",
        "/api/v1/finance/summary",
        "/api/v1/finance/currencies",
        "/api/v1/money/workspace",
        "/api/v1/money/summaries",
        "/api/v1/integrations/monobank/connection",
        "/api/v1/integrations/monobank/sync",
        "/api/v1/integrations/monobank/accounts/{account_id}",
        "/api/v1/integrations/monobank/accounts/{account_id}/transactions",
        "/api/v1/wealth/accounts",
        "/api/v1/wealth/savings-goals",
        "/api/v1/wealth/net-worth-snapshots/capture",
        "/api/v1/health/weights",
        "/api/v1/health/nutrition",
        "/api/v1/health/summary",
    }

    assert expected_paths <= set(paths)
    assert not any("privatbank" in path for path in paths)
    assert schema["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == ("bearer")

    protected_prefixes = (
        "/api/v1/workouts",
        "/api/v1/finance",
        "/api/v1/money",
        "/api/v1/wealth",
        "/api/v1/health",
        "/api/v1/integrations",
    )
    for path, operations in paths.items():
        if not path.startswith(protected_prefixes):
            continue
        for operation in operations.values():
            assert operation["security"] == [{"HTTPBearer": []}], path

    assert "security" not in paths["/api/v1/auth/register"]["post"]
    assert "security" not in paths["/api/v1/auth/login"]["post"]
    assert paths["/api/v1/auth/me"]["get"]["security"] == [{"HTTPBearer": []}]
