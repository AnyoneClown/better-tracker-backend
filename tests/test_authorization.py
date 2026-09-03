from decimal import Decimal

from httpx import AsyncClient

SECOND_USER_EMAIL = "second@example.com"
SECOND_USER_PASSWORD = "SecondPassword1!"


async def register_and_login_second_user(client: AsyncClient) -> dict[str, str]:
    registration = await client.post(
        "/api/v1/auth/register",
        json={"email": SECOND_USER_EMAIL, "password": SECOND_USER_PASSWORD},
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": SECOND_USER_EMAIL, "password": SECOND_USER_PASSWORD},
    )
    assert registration.status_code == 201, registration.text
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_users_cannot_read_or_mutate_each_others_resources(
    api_client: AsyncClient,
) -> None:
    workout = await api_client.post(
        "/api/v1/workouts",
        json={
            "name": "Private workout",
            "performed_at": "2026-07-25T18:00:00+03:00",
            "sets": [{"exercise": "Squat", "set_number": 1, "reps": 5}],
        },
    )
    transaction = await api_client.post(
        "/api/v1/finance/transactions",
        json={
            "kind": "expense",
            "amount": "10.00",
            "category": "food",
            "occurred_on": "2026-07-25",
        },
    )
    budget = await api_client.post(
        "/api/v1/finance/budgets",
        json={
            "year": 2026,
            "month": 7,
            "category": "food",
            "limit_amount": "100.00",
        },
    )
    account = await api_client.post(
        "/api/v1/wealth/accounts",
        json={
            "name": "Private account",
            "account_type": "asset",
            "category": "cash",
            "balance": "100.00",
        },
    )
    goal = await api_client.post(
        "/api/v1/wealth/savings-goals",
        json={
            "name": "Private goal",
            "target_amount": "500.00",
            "current_amount": "50.00",
        },
    )
    contribution = await api_client.post(
        f"/api/v1/wealth/savings-goals/{goal.json()['id']}/contributions",
        json={
            "kind": "contribution",
            "amount": "5.00",
            "occurred_on": "2026-07-25",
        },
    )
    weight = await api_client.post(
        "/api/v1/health/weights",
        json={"recorded_on": "2026-07-25", "weight_kg": "80.00"},
    )
    nutrition = await api_client.post(
        "/api/v1/health/nutrition",
        json={"recorded_on": "2026-07-25", "calories": 2000},
    )
    snapshot = await api_client.post(
        "/api/v1/wealth/net-worth-snapshots/capture",
        json={"currency": "USD"},
    )
    created = (
        workout,
        transaction,
        budget,
        account,
        goal,
        contribution,
        weight,
        nutrition,
        snapshot,
    )
    assert all(response.status_code == 201 for response in created)

    second_user_headers = await register_and_login_second_user(api_client)
    owner_paths = (
        f"/api/v1/workouts/{workout.json()['id']}",
        f"/api/v1/finance/transactions/{transaction.json()['id']}",
        f"/api/v1/finance/budgets/{budget.json()['id']}",
        f"/api/v1/wealth/accounts/{account.json()['id']}",
        f"/api/v1/wealth/savings-goals/{goal.json()['id']}",
        (
            "/api/v1/wealth/savings-contributions/"
            f"{contribution.json()['contribution']['id']}"
        ),
        f"/api/v1/health/weights/{weight.json()['id']}",
        f"/api/v1/health/nutrition/{nutrition.json()['id']}",
        f"/api/v1/wealth/net-worth-snapshots/{snapshot.json()['id']}",
    )
    for path in owner_paths:
        response = await api_client.get(path, headers=second_user_headers)
        assert response.status_code == 404, (path, response.text)

    hidden_goal_contributions = await api_client.get(
        f"/api/v1/wealth/savings-goals/{goal.json()['id']}/contributions",
        headers=second_user_headers,
    )
    hidden_workout_update = await api_client.patch(
        f"/api/v1/workouts/{workout.json()['id']}",
        json={"name": "Stolen"},
        headers=second_user_headers,
    )
    hidden_workout_delete = await api_client.delete(
        f"/api/v1/workouts/{workout.json()['id']}",
        headers=second_user_headers,
    )
    assert hidden_goal_contributions.status_code == 404
    assert hidden_workout_update.status_code == 404
    assert hidden_workout_delete.status_code == 404

    second_transaction = await api_client.post(
        "/api/v1/finance/transactions",
        json={
            "kind": "expense",
            "amount": "12.00",
            "category": "transport",
            "occurred_on": "2026-07-26",
        },
        headers=second_user_headers,
    )
    assert second_transaction.status_code == 201
    bulk_deleted = await api_client.delete(
        "/api/v1/finance/transactions",
        headers=second_user_headers,
    )
    assert bulk_deleted.status_code == 200
    assert bulk_deleted.json() == {"deleted_count": 1}
    owner_transaction = await api_client.get(
        f"/api/v1/finance/transactions/{transaction.json()['id']}"
    )
    assert owner_transaction.status_code == 200


async def test_lists_summaries_and_unique_values_are_scoped_per_user(
    api_client: AsyncClient,
) -> None:
    owner_budget = await api_client.post(
        "/api/v1/finance/budgets",
        json={
            "year": 2026,
            "month": 7,
            "category": "food",
            "limit_amount": "100.00",
        },
    )
    owner_account = await api_client.post(
        "/api/v1/wealth/accounts",
        json={
            "name": "Shared name",
            "account_type": "asset",
            "category": "cash",
            "balance": "100.00",
        },
    )
    owner_weight = await api_client.post(
        "/api/v1/health/weights",
        json={"recorded_on": "2026-07-25", "weight_kg": "80.00"},
    )
    assert owner_budget.status_code == owner_account.status_code == 201
    assert owner_weight.status_code == 201

    second_user_headers = await register_and_login_second_user(api_client)
    second_budget = await api_client.post(
        "/api/v1/finance/budgets",
        json={
            "year": 2026,
            "month": 7,
            "category": "food",
            "limit_amount": "250.00",
        },
        headers=second_user_headers,
    )
    second_account = await api_client.post(
        "/api/v1/wealth/accounts",
        json={
            "name": "Shared name",
            "account_type": "asset",
            "category": "cash",
            "balance": "300.00",
        },
        headers=second_user_headers,
    )
    second_weight = await api_client.post(
        "/api/v1/health/weights",
        json={"recorded_on": "2026-07-25", "weight_kg": "70.00"},
        headers=second_user_headers,
    )
    assert second_budget.status_code == second_account.status_code == 201
    assert second_weight.status_code == 201

    budgets = await api_client.get(
        "/api/v1/finance/budgets",
        headers=second_user_headers,
    )
    finance_summary = await api_client.get(
        "/api/v1/finance/summary?year=2026&month=7&currency=USD",
        headers=second_user_headers,
    )
    wealth_summary = await api_client.get(
        "/api/v1/wealth/summary?currency=USD",
        headers=second_user_headers,
    )
    health_summary = await api_client.get(
        "/api/v1/health/summary",
        headers=second_user_headers,
    )
    workouts = await api_client.get(
        "/api/v1/workouts",
        headers=second_user_headers,
    )
    assert budgets.json()["total"] == 1
    assert Decimal(finance_summary.json()["total_budget"]) == Decimal("250.00")
    assert Decimal(wealth_summary.json()["assets"]) == Decimal("300.00")
    assert Decimal(health_summary.json()["latest_weight_kg"]) == Decimal("70.00")
    assert workouts.json()["total"] == 0
