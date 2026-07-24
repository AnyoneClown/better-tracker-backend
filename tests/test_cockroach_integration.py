import asyncio
import os
import re
from collections.abc import Iterator
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
def migrated_database() -> Iterator[None]:
    database_url = make_url(os.environ["DATABASE_URL"])
    database_name = database_url.database or ""
    if re.fullmatch(r"tracker_test(?:_[a-z0-9_]+)?", database_name) is None:
        raise RuntimeError(
            "integration DATABASE_URL must use tracker_test or "
            "a tracker_test_* database"
        )

    admin_execute(f'DROP DATABASE IF EXISTS "{database_name}" CASCADE')
    admin_execute(f'CREATE DATABASE "{database_name}"')
    try:
        alembic_config = Config("alembic.ini")
        command.upgrade(alembic_config, "head")
        command.check(alembic_config)
        yield
    finally:
        admin_execute(f'DROP DATABASE IF EXISTS "{database_name}" CASCADE')


def test_all_trackers_against_cockroach() -> None:
    with TestClient(app) as client:
        assert client.get("/readyz").status_code == 200

        empty_wealth = client.get("/api/v1/wealth/summary?currency=USD")
        empty_health = client.get("/api/v1/health/summary")
        empty_workouts = client.get("/api/v1/workouts/summary")
        assert (
            empty_wealth.status_code
            == empty_health.status_code
            == empty_workouts.status_code
            == 200
        )
        assert Decimal(empty_wealth.json()["net_worth"]) == 0
        assert empty_health.json()["total_calories"] == 0
        assert empty_workouts.json()["workout_count"] == 0
        assert empty_workouts.json()["average_duration_minutes"] is None
        assert Decimal(empty_workouts.json()["total_volume_kg"]) == 0

        workout = client.post(
            "/api/v1/workouts",
            json={
                "name": "Integration workout",
                "performed_at": "2026-07-24T18:00:00+03:00",
                "duration_minutes": 45,
                "sets": [
                    {
                        "exercise": " Squat ",
                        "set_number": 1,
                        "reps": 8,
                        "weight_kg": "80.000",
                    },
                    {
                        "exercise": "SQUAT",
                        "set_number": 2,
                        "reps": 5,
                        "weight_kg": "100.000",
                    },
                    {
                        "exercise": "Run",
                        "set_number": 1,
                        "distance_km": "3.500",
                        "duration_seconds": 1200,
                    },
                ],
            },
        )
        assert workout.status_code == 201
        assert len(workout.json()["sets"]) == 3
        assert {item["exercise"] for item in workout.json()["sets"]} == {
            "run",
            "squat",
        }

        second_workout = client.post(
            "/api/v1/workouts",
            json={
                "name": "Integration recovery workout",
                "performed_at": "2026-07-25T18:00:00+03:00",
                "duration_minutes": 30,
                "sets": [
                    {
                        "exercise": "Squat",
                        "set_number": 1,
                        "reps": 10,
                        "weight_kg": "50.000",
                    }
                ],
            },
        )
        assert second_workout.status_code == 201

        workout_summary = client.get("/api/v1/workouts/summary")
        assert workout_summary.status_code == 200
        workout_summary_body = workout_summary.json()
        assert workout_summary_body["workout_count"] == 2
        assert workout_summary_body["total_duration_minutes"] == 75
        assert Decimal(workout_summary_body["average_duration_minutes"]) == Decimal(
            "37.50"
        )
        assert workout_summary_body["total_sets"] == 4
        assert workout_summary_body["total_reps"] == 23
        assert Decimal(workout_summary_body["total_volume_kg"]) == Decimal("1640.000")
        assert Decimal(workout_summary_body["total_distance_km"]) == Decimal("3.500")
        assert workout_summary_body["total_set_duration_seconds"] == 1200
        exercise_summaries = {
            item["exercise"]: item for item in workout_summary_body["exercises"]
        }
        assert exercise_summaries["squat"]["sets"] == 3
        assert exercise_summaries["squat"]["total_reps"] == 23
        assert Decimal(exercise_summaries["squat"]["volume_kg"]) == Decimal("1640.000")
        assert Decimal(exercise_summaries["run"]["distance_km"]) == Decimal("3.500")
        assert exercise_summaries["run"]["duration_seconds"] == 1200

        expense = client.post(
            "/api/v1/finance/transactions",
            json={
                "kind": "expense",
                "amount": "200.10",
                "category": " Food ",
                "occurred_on": "2026-07-12",
                "currency": "USD",
            },
        )
        budget_payload = {
            "year": 2026,
            "month": 7,
            "category": "FOOD",
            "currency": "USD",
            "limit_amount": "500.00",
        }
        budget = client.post("/api/v1/finance/budgets", json=budget_payload)
        duplicate_budget = client.post(
            "/api/v1/finance/budgets",
            json=budget_payload,
        )
        assert expense.status_code == budget.status_code == 201
        assert expense.json()["category"] == budget.json()["category"] == "food"
        assert duplicate_budget.status_code == 409
        filtered_expenses = client.get(
            "/api/v1/finance/transactions",
            params={"category": "FOOD", "currency": "usd"},
        )
        assert filtered_expenses.status_code == 200
        assert filtered_expenses.json()["total"] == 1
        assert filtered_expenses.json()["items"][0]["id"] == expense.json()["id"]
        finance = client.get("/api/v1/finance/summary?year=2026&month=7&currency=USD")
        assert finance.status_code == 200
        assert Decimal(finance.json()["budget_remaining"]) == Decimal("299.90")
        assert [item["category"] for item in finance.json()["categories"]] == ["food"]

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
        account_page = client.get(
            "/api/v1/wealth/accounts",
            params={"offset": 1, "limit": 1},
        )
        assert account_page.status_code == 200
        assert account_page.json()["total"] == 2
        assert account_page.json()["offset"] == 1
        assert account_page.json()["limit"] == 1
        assert [item["id"] for item in account_page.json()["items"]] == [
            account.json()["id"]
        ]
        assert (
            client.patch(
                f"/api/v1/wealth/accounts/{account.json()['id']}",
                json={"balance": None},
            ).status_code
            == 422
        )

        goal = client.post(
            "/api/v1/wealth/savings-goals",
            json={
                "name": "Integration goal",
                "target_amount": "1000.00",
                "currency": "USD",
            },
        )
        assert goal.status_code == 201
        goal_id = goal.json()["id"]
        assert Decimal(goal.json()["current_amount"]) == Decimal("0.00")
        goal_page = client.get(
            "/api/v1/wealth/savings-goals",
            params={"offset": 0, "limit": 1},
        )
        assert goal_page.status_code == 200
        assert goal_page.json()["total"] == 1
        assert goal_page.json()["offset"] == 0
        assert goal_page.json()["limit"] == 1
        assert goal_page.json()["items"][0]["id"] == goal_id

        rejected_initial_withdrawal = client.post(
            f"/api/v1/wealth/savings-goals/{goal_id}/contributions",
            json={
                "kind": "withdrawal",
                "amount": "1.00",
                "occurred_on": "2026-06-30",
            },
        )
        assert rejected_initial_withdrawal.status_code == 422
        goal_after_rejected_withdrawal = client.get(
            f"/api/v1/wealth/savings-goals/{goal_id}"
        )
        assert Decimal(
            goal_after_rejected_withdrawal.json()["current_amount"]
        ) == Decimal("0.00")

        contribution = client.post(
            f"/api/v1/wealth/savings-goals/{goal_id}/contributions",
            json={
                "kind": "contribution",
                "amount": "100.00",
                "occurred_on": "2026-07-01",
            },
        )
        assert contribution.status_code == 201
        contribution_id = contribution.json()["contribution"]["id"]
        assert Decimal(contribution.json()["goal_current_amount"]) == Decimal("100.00")
        assert Decimal(contribution.json()["contribution"]["signed_amount"]) == Decimal(
            "100.00"
        )

        withdrawal = client.post(
            f"/api/v1/wealth/savings-goals/{goal_id}/contributions",
            json={
                "kind": "withdrawal",
                "amount": "20.00",
                "occurred_on": "2026-07-02",
            },
        )
        assert withdrawal.status_code == 201
        withdrawal_id = withdrawal.json()["contribution"]["id"]
        assert Decimal(withdrawal.json()["goal_current_amount"]) == Decimal("80.00")
        assert Decimal(withdrawal.json()["contribution"]["signed_amount"]) == Decimal(
            "-20.00"
        )

        contribution_page = client.get(
            f"/api/v1/wealth/savings-goals/{goal_id}/contributions",
            params={"offset": 1, "limit": 1},
        )
        assert contribution_page.status_code == 200
        assert contribution_page.json()["total"] == 2
        assert contribution_page.json()["offset"] == 1
        assert contribution_page.json()["limit"] == 1
        assert contribution_page.json()["items"][0]["id"] == contribution_id

        contribution_detail = client.get(
            f"/api/v1/wealth/savings-contributions/{contribution_id}"
        )
        assert contribution_detail.status_code == 200
        assert contribution_detail.json()["id"] == contribution_id

        adjusted_contribution = client.patch(
            f"/api/v1/wealth/savings-contributions/{contribution_id}",
            json={"amount": "120.00", "notes": "Adjusted deposit"},
        )
        assert adjusted_contribution.status_code == 200
        assert Decimal(adjusted_contribution.json()["goal_current_amount"]) == Decimal(
            "100.00"
        )
        assert (
            adjusted_contribution.json()["contribution"]["notes"] == "Adjusted deposit"
        )

        overdraft = client.patch(
            f"/api/v1/wealth/savings-contributions/{withdrawal_id}",
            json={"amount": "200.00"},
        )
        assert overdraft.status_code == 422
        unchanged_withdrawal = client.get(
            f"/api/v1/wealth/savings-contributions/{withdrawal_id}"
        )
        assert unchanged_withdrawal.status_code == 200
        assert Decimal(unchanged_withdrawal.json()["amount"]) == Decimal("20.00")
        unchanged_goal = client.get(f"/api/v1/wealth/savings-goals/{goal_id}")
        assert Decimal(unchanged_goal.json()["current_amount"]) == Decimal("100.00")

        protected_contribution = client.delete(
            f"/api/v1/wealth/savings-contributions/{contribution_id}"
        )
        assert protected_contribution.status_code == 409
        deleted_withdrawal = client.delete(
            f"/api/v1/wealth/savings-contributions/{withdrawal_id}"
        )
        assert deleted_withdrawal.status_code == 204
        goal_after_withdrawal_delete = client.get(
            f"/api/v1/wealth/savings-goals/{goal_id}"
        )
        assert Decimal(
            goal_after_withdrawal_delete.json()["current_amount"]
        ) == Decimal("120.00")
        deleted_contribution = client.delete(
            f"/api/v1/wealth/savings-contributions/{contribution_id}"
        )
        assert deleted_contribution.status_code == 204
        assert (
            client.get(
                f"/api/v1/wealth/savings-contributions/{contribution_id}"
            ).status_code
            == 404
        )
        goal_after_ledger_clear = client.get(f"/api/v1/wealth/savings-goals/{goal_id}")
        assert Decimal(goal_after_ledger_clear.json()["current_amount"]) == Decimal(
            "0.00"
        )

        wealth = client.get("/api/v1/wealth/summary?currency=USD")
        assert wealth.status_code == 200
        assert Decimal(wealth.json()["net_worth"]) == Decimal("1150.00")
        assert Decimal(wealth.json()["savings_goal_target"]) == Decimal("1000.00")
        assert Decimal(wealth.json()["savings_goal_current"]) == Decimal("0.00")

        backdated_snapshot = client.post(
            "/api/v1/wealth/net-worth-snapshots/capture",
            json={
                "currency": "USD",
                "recorded_at": "2026-07-01T00:00:00+00:00",
            },
        )
        assert backdated_snapshot.status_code == 422
        snapshot = client.post(
            "/api/v1/wealth/net-worth-snapshots/capture",
            json={"currency": "USD", "notes": "Current integration snapshot"},
        )
        assert snapshot.status_code == 201
        snapshot_body = snapshot.json()
        assert snapshot_body["recorded_at"]
        assert Decimal(snapshot_body["net_worth"]) == Decimal("1150.00")
        snapshot_detail = client.get(
            f"/api/v1/wealth/net-worth-snapshots/{snapshot_body['id']}"
        )
        assert snapshot_detail.status_code == 200
        assert snapshot_detail.json() == snapshot_body
        snapshot_page = client.get(
            "/api/v1/wealth/net-worth-snapshots",
            params={"offset": 0, "limit": 1},
        )
        assert snapshot_page.status_code == 200
        assert snapshot_page.json()["total"] == 1
        assert snapshot_page.json()["offset"] == 0
        assert snapshot_page.json()["limit"] == 1
        assert snapshot_page.json()["items"][0]["id"] == snapshot_body["id"]

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
        weight_page = client.get(
            "/api/v1/health/weights",
            params={"offset": 1, "limit": 1},
        )
        assert weight_page.status_code == 200
        assert weight_page.json()["total"] == 2
        assert weight_page.json()["offset"] == 1
        assert weight_page.json()["limit"] == 1
        assert weight_page.json()["items"][0]["id"] == first_weight.json()["id"]
        nutrition_page = client.get(
            "/api/v1/health/nutrition",
            params={"offset": 0, "limit": 1},
        )
        assert nutrition_page.status_code == 200
        assert nutrition_page.json()["total"] == 1
        assert nutrition_page.json()["offset"] == 0
        assert nutrition_page.json()["limit"] == 1
        assert nutrition_page.json()["items"][0]["id"] == nutrition.json()["id"]
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
