from decimal import Decimal
from typing import cast

from httpx import AsyncClient


async def post_json(
    client: AsyncClient,
    path: str,
    payload: dict[str, object],
) -> dict[str, object]:
    response = await client.post(path, json=payload)
    assert response.status_code == 201, response.text
    return cast(dict[str, object], response.json())


async def create_goal(
    client: AsyncClient,
    name: str,
    currency: str,
) -> dict[str, object]:
    return await post_json(
        client,
        "/api/v1/wealth/savings-goals",
        {
            "name": name,
            "target_amount": "1000.00",
            "currency": currency,
        },
    )


async def create_contribution(
    client: AsyncClient,
    goal_id: object,
    occurred_on: str,
) -> dict[str, object]:
    response = await post_json(
        client,
        f"/api/v1/wealth/savings-goals/{goal_id}/contributions",
        {
            "kind": "contribution",
            "amount": "25.00",
            "occurred_on": occurred_on,
        },
    )
    return cast(dict[str, object], response["contribution"])


async def create_transaction(
    client: AsyncClient,
    *,
    occurred_on: str,
    category: str,
    amount: str,
    kind: str = "expense",
    currency: str = "UAH",
) -> dict[str, object]:
    return await post_json(
        client,
        "/api/v1/finance/transactions",
        {
            "kind": kind,
            "amount": amount,
            "category": category,
            "occurred_on": occurred_on,
            "currency": currency,
        },
    )


async def test_money_workspace_returns_one_filtered_owned_payload(
    api_client: AsyncClient,
) -> None:
    food = await create_transaction(
        api_client,
        occurred_on="2026-07-10",
        category="food",
        amount="125.50",
    )
    await create_transaction(
        api_client,
        occurred_on="2026-07-11",
        category="travel",
        amount="40.00",
    )
    await create_transaction(
        api_client,
        occurred_on="2026-07-01",
        category="salary",
        amount="2000.00",
        kind="income",
    )
    await post_json(
        api_client,
        "/api/v1/finance/budgets",
        {
            "year": 2026,
            "month": 7,
            "category": "food",
            "limit_amount": "500.00",
            "currency": "UAH",
        },
    )
    await post_json(
        api_client,
        "/api/v1/wealth/accounts",
        {
            "name": "Cash",
            "account_type": "asset",
            "category": "cash",
            "balance": "300.00",
            "currency": "UAH",
            "include_in_net_worth": True,
            "is_savings": False,
        },
    )

    owner_goal = await create_goal(api_client, "Owner UAH", "UAH")
    owner_july = await create_contribution(api_client, owner_goal["id"], "2026-07-05")
    await create_contribution(api_client, owner_goal["id"], "2026-06-30")
    euro_goal = await create_goal(api_client, "Owner EUR", "EUR")
    await create_contribution(api_client, euro_goal["id"], "2026-07-05")

    owner_authorization = api_client.headers["Authorization"]
    registration = await api_client.post(
        "/api/v1/auth/register",
        json={"email": "other@example.com", "password": "OtherPassword1!"},
    )
    assert registration.status_code == 201, registration.text
    login = await api_client.post(
        "/api/v1/auth/login",
        json={"email": "other@example.com", "password": "OtherPassword1!"},
    )
    assert login.status_code == 200, login.text
    api_client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    other_goal = await create_goal(api_client, "Other UAH", "UAH")
    await create_contribution(api_client, other_goal["id"], "2026-07-06")
    api_client.headers["Authorization"] = owner_authorization

    response = await api_client.get(
        "/api/v1/money/workspace",
        params={
            "year": 2026,
            "month": 7,
            "currency": "uah",
            "category": " Food ",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert set(body) == {
        "finance",
        "transactions",
        "budgets",
        "wealth",
        "accounts",
        "goals",
        "contributions",
        "snapshots",
        "currencies",
        "monobank",
    }
    assert body["finance"]["currency"] == "UAH"
    assert Decimal(body["finance"]["total_expenses"]) == Decimal("165.50")
    assert [item["id"] for item in body["transactions"]] == [food["id"]]
    assert len(body["budgets"]) == 1
    assert len(body["accounts"]) == 1
    assert [item["id"] for item in body["goals"]] == [owner_goal["id"]]
    assert [item["id"] for item in body["contributions"]] == [owner_july["id"]]
    assert body["snapshots"] == []
    assert body["currencies"] == ["UAH", "EUR"]
    assert body["monobank"] == {
        "connected": False,
        "id": None,
        "external_client_id": None,
        "client_name": None,
        "permissions": None,
        "client_metadata": None,
        "sync_status": None,
        "sync_progress_current": 0,
        "sync_progress_total": 0,
        "sync_error": None,
        "sync_date_from": None,
        "sync_date_to": None,
        "connected_at": None,
        "last_sync_started_at": None,
        "last_sync_completed_at": None,
        "accounts": [],
        "jars": [],
    }


async def test_money_summaries_returns_at_most_twelve_ordered_months(
    api_client: AsyncClient,
) -> None:
    await create_transaction(
        api_client,
        occurred_on="2026-07-10",
        category="food",
        amount="10.00",
    )
    await create_transaction(
        api_client,
        occurred_on="2026-08-10",
        category="food",
        amount="20.00",
    )

    response = await api_client.get(
        "/api/v1/money/summaries",
        params={
            "start_month": "2026-07",
            "end_month": "2026-08",
            "currency": "UAH",
        },
    )
    assert response.status_code == 200, response.text
    assert [
        (item["year"], item["month"], Decimal(item["total_expenses"]))
        for item in response.json()
    ] == [
        (2026, 7, Decimal("10.00")),
        (2026, 8, Decimal("20.00")),
    ]

    for start_month, end_month in (
        ("2026-08", "2026-07"),
        ("2025-08", "2026-08"),
        ("0000-01", "0000-01"),
        ("2026-13", "2026-13"),
    ):
        invalid = await api_client.get(
            "/api/v1/money/summaries",
            params={
                "start_month": start_month,
                "end_month": end_month,
                "currency": "UAH",
            },
        )
        assert invalid.status_code == 422
