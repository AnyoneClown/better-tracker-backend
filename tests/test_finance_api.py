from decimal import Decimal
from uuid import uuid4

from httpx import AsyncClient


async def create_transaction(
    client: AsyncClient,
    *,
    kind: str,
    amount: str,
    category: str,
    occurred_on: str,
    currency: str = "USD",
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/finance/transactions",
        json={
            "kind": kind,
            "amount": amount,
            "category": category,
            "occurred_on": occurred_on,
            "currency": currency,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def create_budget(
    client: AsyncClient,
    *,
    year: int,
    month: int,
    category: str,
    limit_amount: str,
    currency: str = "USD",
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/finance/budgets",
        json={
            "year": year,
            "month": month,
            "category": category,
            "limit_amount": limit_amount,
            "currency": currency,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_transaction_crud_filters_and_pagination(api_client: AsyncClient) -> None:
    salary = await create_transaction(
        api_client,
        kind="income",
        amount="5000.00",
        category=" Salary ",
        occurred_on="2026-07-01",
    )
    food = await create_transaction(
        api_client,
        kind="expense",
        amount="200.10",
        category="Food",
        occurred_on="2026-07-10",
        currency="usd",
    )
    await create_transaction(
        api_client,
        kind="expense",
        amount="300.00",
        category="Travel",
        occurred_on="2026-06-30",
        currency="EUR",
    )
    assert salary["category"] == "salary"
    assert food["currency"] == "USD"

    filtered = await api_client.get(
        "/api/v1/finance/transactions",
        params={
            "kind": "expense",
            "category": " food ",
            "currency": "usd",
            "start_date": "2026-07-01",
            "end_date": "2026-07-31",
        },
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["id"] == food["id"]

    page = await api_client.get(
        "/api/v1/finance/transactions",
        params={"offset": 1, "limit": 1},
    )
    assert page.status_code == 200
    assert page.json()["total"] == 3
    assert page.json()["offset"] == 1
    assert page.json()["limit"] == 1
    assert page.json()["items"][0]["id"] == salary["id"]

    fetched = await api_client.get(f"/api/v1/finance/transactions/{salary['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == salary["id"]

    updated = await api_client.patch(
        f"/api/v1/finance/transactions/{salary['id']}",
        json={"amount": "5100.25", "description": "July salary"},
    )
    assert updated.status_code == 200, updated.text
    assert Decimal(updated.json()["amount"]) == Decimal("5100.25")
    assert updated.json()["description"] == "July salary"

    deleted = await api_client.delete(f"/api/v1/finance/transactions/{salary['id']}")
    assert deleted.status_code == 204
    assert (
        await api_client.get(f"/api/v1/finance/transactions/{salary['id']}")
    ).status_code == 404


async def test_delete_all_transactions_is_idempotent(api_client: AsyncClient) -> None:
    for transaction in (
        ("income", "5000.00", "salary", "2026-07-01", "USD"),
        ("expense", "200.10", "food", "2026-07-10", "USD"),
        ("expense", "300.00", "travel", "2026-06-30", "EUR"),
    ):
        await create_transaction(
            api_client,
            kind=transaction[0],
            amount=transaction[1],
            category=transaction[2],
            occurred_on=transaction[3],
            currency=transaction[4],
        )

    deleted = await api_client.delete("/api/v1/finance/transactions")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"deleted_count": 3}

    remaining = await api_client.get("/api/v1/finance/transactions")
    assert remaining.status_code == 200
    assert remaining.json()["total"] == 0

    deleted_again = await api_client.delete("/api/v1/finance/transactions")
    assert deleted_again.status_code == 200
    assert deleted_again.json() == {"deleted_count": 0}


async def test_budget_crud_filters_and_pagination(api_client: AsyncClient) -> None:
    july_food = await create_budget(
        api_client,
        year=2026,
        month=7,
        category=" Food ",
        limit_amount="500.00",
    )
    await create_budget(
        api_client,
        year=2026,
        month=8,
        category="food",
        limit_amount="550.00",
    )
    await create_budget(
        api_client,
        year=2026,
        month=7,
        category="travel",
        limit_amount="900.00",
        currency="EUR",
    )
    assert july_food["category"] == "food"

    filtered = await api_client.get(
        "/api/v1/finance/budgets",
        params={"year": 2026, "month": 7, "currency": "usd"},
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["id"] == july_food["id"]

    page = await api_client.get(
        "/api/v1/finance/budgets",
        params={"offset": 1, "limit": 1},
    )
    assert page.status_code == 200
    assert page.json()["total"] == 3
    assert len(page.json()["items"]) == 1

    fetched = await api_client.get(f"/api/v1/finance/budgets/{july_food['id']}")
    assert fetched.status_code == 200

    updated = await api_client.patch(
        f"/api/v1/finance/budgets/{july_food['id']}",
        json={"limit_amount": "625.50"},
    )
    assert updated.status_code == 200, updated.text
    assert Decimal(updated.json()["limit_amount"]) == Decimal("625.50")

    deleted = await api_client.delete(f"/api/v1/finance/budgets/{july_food['id']}")
    assert deleted.status_code == 204
    assert (
        await api_client.get(f"/api/v1/finance/budgets/{july_food['id']}")
    ).status_code == 404


async def test_finance_summary_is_decimal_exact_and_category_aware(
    api_client: AsyncClient,
) -> None:
    for transaction in (
        ("income", "5000.00", "salary", "2026-07-01"),
        ("expense", "200.10", "food", "2026-07-10"),
        ("expense", "50.00", "fun", "2026-07-11"),
        ("expense", "999.00", "ignored", "2026-06-30"),
    ):
        await create_transaction(
            api_client,
            kind=transaction[0],
            amount=transaction[1],
            category=transaction[2],
            occurred_on=transaction[3],
        )

    await create_budget(
        api_client,
        year=2026,
        month=7,
        category="food",
        limit_amount="500.00",
    )
    await create_budget(
        api_client,
        year=2026,
        month=7,
        category="housing",
        limit_amount="1000.00",
    )

    response = await api_client.get(
        "/api/v1/finance/summary",
        params={"year": 2026, "month": 7, "currency": "usd"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["currency"] == "USD"
    assert Decimal(body["total_income"]) == Decimal("5000.00")
    assert Decimal(body["total_expenses"]) == Decimal("250.10")
    assert Decimal(body["net"]) == Decimal("4749.90")
    assert Decimal(body["total_budget"]) == Decimal("1500.00")
    assert Decimal(body["budget_remaining"]) == Decimal("1249.90")

    categories = {item["category"]: item for item in body["categories"]}
    assert Decimal(categories["food"]["budget_remaining"]) == Decimal("299.90")
    assert categories["fun"]["budget"] is None
    assert Decimal(categories["salary"]["income"]) == Decimal("5000.00")
    assert Decimal(categories["housing"]["budget"]) == Decimal("1000.00")


async def test_finance_validation_and_missing_resources(
    api_client: AsyncClient,
) -> None:
    invalid_transaction = await api_client.post(
        "/api/v1/finance/transactions",
        json={
            "kind": "expense",
            "amount": 0,
            "category": "food",
            "occurred_on": "2026-07-01",
            "unexpected": True,
        },
    )
    assert invalid_transaction.status_code == 422
    assert (
        await api_client.get(
            "/api/v1/finance/transactions",
            params={"start_date": "2026-08-01", "end_date": "2026-07-01"},
        )
    ).status_code == 422
    assert (
        await api_client.get(
            "/api/v1/finance/summary",
            params={"year": 2026, "month": 13},
        )
    ).status_code == 422

    transaction = await create_transaction(
        api_client,
        kind="expense",
        amount="10.00",
        category="food",
        occurred_on="2026-07-01",
    )
    assert (
        await api_client.patch(
            f"/api/v1/finance/transactions/{transaction['id']}",
            json={},
        )
    ).status_code == 422
    assert (
        await api_client.patch(
            f"/api/v1/finance/transactions/{transaction['id']}",
            json={"amount": None},
        )
    ).status_code == 422

    missing_id = uuid4()
    for path in (
        f"/api/v1/finance/transactions/{missing_id}",
        f"/api/v1/finance/budgets/{missing_id}",
    ):
        assert (await api_client.get(path)).status_code == 404
        assert (await api_client.delete(path)).status_code == 404
