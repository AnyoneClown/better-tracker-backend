import asyncio
import os
import re
from decimal import Decimal

import pytest

if os.getenv("RUN_COCKROACH_INTEGRATION") != "1":
    pytest.skip(
        "set RUN_COCKROACH_INTEGRATION=1 to run CockroachDB integration tests",
        allow_module_level=True,
    )

import asyncpg  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from alembic import command  # noqa: E402
from app.main import app  # noqa: E402

pytestmark = pytest.mark.integration


def admin_execute(statement: str) -> None:
    database_url = make_url(os.environ["DATABASE_URL"])

    async def execute() -> None:
        connection = await asyncpg.connect(
            user=database_url.username or "root",
            password=database_url.password,
            host=database_url.host or "localhost",
            port=database_url.port or 26257,
            database="defaultdb",
            ssl=False,
        )
        try:
            await connection.execute(statement)
        finally:
            await connection.close()

    asyncio.run(execute())


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> None:
    database_url = make_url(os.environ["DATABASE_URL"])
    database_name = database_url.database or ""
    if re.fullmatch(r"tracker_test(?:_[a-z0-9_]+)?", database_name) is None:
        raise RuntimeError(
            "integration DATABASE_URL must use tracker_test or "
            "a tracker_test_* database"
        )

    admin_execute(f'DROP DATABASE IF EXISTS "{database_name}" CASCADE')
    admin_execute(f'CREATE DATABASE "{database_name}"')
    alembic_config = Config("alembic.ini")
    command.upgrade(alembic_config, "head")
    command.check(alembic_config)

    yield

    admin_execute(f'DROP DATABASE IF EXISTS "{database_name}" CASCADE')


def test_all_trackers_against_cockroach() -> None:
    with TestClient(app) as client:
        assert client.get("/readyz").status_code == 200

        empty_wealth = client.get("/api/v1/wealth/summary?currency=USD")
        empty_health = client.get("/api/v1/health/summary")
        assert empty_wealth.status_code == empty_health.status_code == 200
        assert Decimal(empty_wealth.json()["net_worth"]) == 0
        assert empty_health.json()["total_calories"] == 0

        workout = client.post(
            "/api/v1/workouts",
            json={
                "name": "Integration workout",
                "performed_at": "2026-07-24T18:00:00+03:00",
                "duration_minutes": 45,
                "sets": [
                    {
                        "exercise": "Squat",
                        "set_number": 1,
                        "reps": 8,
                        "weight_kg": "80.000",
                    }
                ],
            },
        )
        assert workout.status_code == 201
        assert len(workout.json()["sets"]) == 1

        expense = client.post(
            "/api/v1/finance/transactions",
            json={
                "kind": "expense",
                "amount": "200.10",
                "category": "food",
                "occurred_on": "2026-07-12",
                "currency": "USD",
            },
        )
        budget_payload = {
            "year": 2026,
            "month": 7,
            "category": "food",
            "currency": "USD",
            "limit_amount": "500.00",
        }
        budget = client.post("/api/v1/finance/budgets", json=budget_payload)
        duplicate_budget = client.post(
            "/api/v1/finance/budgets",
            json=budget_payload,
        )
        assert expense.status_code == budget.status_code == 201
        assert duplicate_budget.status_code == 409
        finance = client.get("/api/v1/finance/summary?year=2026&month=7&currency=USD")
        assert finance.status_code == 200
        assert Decimal(finance.json()["budget_remaining"]) == Decimal("299.90")

        account = client.post(
            "/api/v1/wealth/accounts",
            json={
                "name": "Savings",
                "account_type": "asset",
                "category": "cash",
                "balance": "1500.00",
                "currency": "USD",
                "is_savings": True,
            },
        )
        liability = client.post(
            "/api/v1/wealth/accounts",
            json={
                "name": "Credit card",
                "account_type": "liability",
                "category": "credit",
                "balance": "350.00",
                "currency": "USD",
            },
        )
        assert account.status_code == liability.status_code == 201
        assert (
            client.patch(
                f"/api/v1/wealth/accounts/{account.json()['id']}",
                json={"balance": None},
            ).status_code
            == 422
        )
        wealth = client.get("/api/v1/wealth/summary?currency=USD")
        assert wealth.status_code == 200
        assert Decimal(wealth.json()["net_worth"]) == Decimal("1150.00")
        assert (
            client.post(
                "/api/v1/wealth/net-worth-snapshots/capture",
                json={"currency": "USD"},
            ).status_code
            == 201
        )

        first_weight = client.post(
            "/api/v1/health/weights",
            json={"recorded_on": "2026-07-20", "weight_kg": "82.40"},
        )
        second_weight = client.post(
            "/api/v1/health/weights",
            json={"recorded_on": "2026-07-24", "weight_kg": "81.75"},
        )
        duplicate_weight = client.post(
            "/api/v1/health/weights",
            json={"recorded_on": "2026-07-24", "weight_kg": "81.50"},
        )
        nutrition = client.post(
            "/api/v1/health/nutrition",
            json={
                "recorded_on": "2026-07-24",
                "calories": 2150,
                "calorie_target": 2200,
            },
        )
        assert first_weight.status_code == second_weight.status_code == 201
        assert duplicate_weight.status_code == 409
        assert nutrition.status_code == 201
        assert (
            client.patch(
                f"/api/v1/health/weights/{first_weight.json()['id']}",
                json={"weight_kg": None},
            ).status_code
            == 422
        )
        health = client.get(
            "/api/v1/health/summary?start_date=2026-07-01&end_date=2026-07-31"
        )
        assert health.status_code == 200
        assert Decimal(health.json()["weight_change_kg"]) == Decimal("-0.65")
        assert health.json()["total_calories"] == 2150
