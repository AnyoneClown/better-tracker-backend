from decimal import Decimal
from uuid import uuid4

from httpx import AsyncClient


async def create_account(
    client: AsyncClient,
    *,
    name: str,
    account_type: str,
    balance: str,
    currency: str = "USD",
    include_in_net_worth: bool = True,
    is_savings: bool = False,
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/wealth/accounts",
        json={
            "name": name,
            "account_type": account_type,
            "category": "cash" if account_type == "asset" else "credit",
            "balance": balance,
            "currency": currency,
            "include_in_net_worth": include_in_net_worth,
            "is_savings": is_savings,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def create_goal(
    client: AsyncClient,
    *,
    name: str,
    target_amount: str = "1000.00",
    currency: str = "USD",
    target_date: str | None = "2026-12-31",
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/wealth/savings-goals",
        json={
            "name": name,
            "target_amount": target_amount,
            "currency": currency,
            "target_date": target_date,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def create_contribution(
    client: AsyncClient,
    goal_id: object,
    *,
    amount: str,
    occurred_on: str,
    kind: str = "contribution",
) -> dict[str, object]:
    response = await client.post(
        f"/api/v1/wealth/savings-goals/{goal_id}/contributions",
        json={
            "kind": kind,
            "amount": amount,
            "occurred_on": occurred_on,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_account_crud_filters_and_pagination(api_client: AsyncClient) -> None:
    bank = await create_account(
        api_client,
        name="Bank",
        account_type="asset",
        balance="1000.00",
        is_savings=True,
    )
    debt = await create_account(
        api_client,
        name="Debt",
        account_type="liability",
        balance="250.00",
    )
    await create_account(
        api_client,
        name="Euro cash",
        account_type="asset",
        balance="300.00",
        currency="EUR",
    )

    filtered = await api_client.get(
        "/api/v1/wealth/accounts",
        params={"account_type": "asset", "currency": "usd"},
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["id"] == bank["id"]

    page = await api_client.get(
        "/api/v1/wealth/accounts",
        params={"offset": 1, "limit": 1},
    )
    assert page.status_code == 200
    assert page.json()["total"] == 3
    assert len(page.json()["items"]) == 1

    fetched = await api_client.get(f"/api/v1/wealth/accounts/{debt['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == debt["id"]

    updated = await api_client.patch(
        f"/api/v1/wealth/accounts/{debt['id']}",
        json={"balance": "225.50", "category": "card"},
    )
    assert updated.status_code == 200, updated.text
    assert Decimal(updated.json()["balance"]) == Decimal("225.50")
    assert updated.json()["category"] == "card"

    invalid_transition = await api_client.patch(
        f"/api/v1/wealth/accounts/{bank['id']}",
        json={"account_type": "liability"},
    )
    assert invalid_transition.status_code == 422

    deleted = await api_client.delete(f"/api/v1/wealth/accounts/{debt['id']}")
    assert deleted.status_code == 204
    assert (
        await api_client.get(f"/api/v1/wealth/accounts/{debt['id']}")
    ).status_code == 404


async def test_savings_goal_crud_filters_and_pagination(
    api_client: AsyncClient,
) -> None:
    emergency = await create_goal(
        api_client,
        name="Emergency fund",
        target_amount="5000.00",
        target_date="2026-10-01",
    )
    await create_goal(
        api_client,
        name="Holiday",
        target_amount="2000.00",
        target_date="2027-01-01",
    )
    await create_goal(
        api_client,
        name="Euro goal",
        target_amount="1000.00",
        currency="EUR",
        target_date="2027-02-01",
    )

    filtered = await api_client.get(
        "/api/v1/wealth/savings-goals",
        params={"currency": "usd"},
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["total"] == 2
    assert len(filtered.json()["items"]) == 2

    page = await api_client.get(
        "/api/v1/wealth/savings-goals",
        params={"offset": 1, "limit": 1},
    )
    assert page.status_code == 200
    assert page.json()["total"] == 3
    assert len(page.json()["items"]) == 1

    fetched = await api_client.get(f"/api/v1/wealth/savings-goals/{emergency['id']}")
    assert fetched.status_code == 200

    updated = await api_client.patch(
        f"/api/v1/wealth/savings-goals/{emergency['id']}",
        json={"target_amount": "6000.00", "notes": "Six months of expenses"},
    )
    assert updated.status_code == 200, updated.text
    assert Decimal(updated.json()["target_amount"]) == Decimal("6000.00")
    assert updated.json()["notes"] == "Six months of expenses"

    assert (
        await api_client.patch(
            f"/api/v1/wealth/savings-goals/{emergency['id']}",
            json={"current_amount": "1.00"},
        )
    ).status_code == 422

    deleted = await api_client.delete(f"/api/v1/wealth/savings-goals/{emergency['id']}")
    assert deleted.status_code == 204
    assert (
        await api_client.get(f"/api/v1/wealth/savings-goals/{emergency['id']}")
    ).status_code == 404


async def test_savings_contribution_ledger_crud_and_overdraft_protection(
    api_client: AsyncClient,
) -> None:
    goal = await create_goal(api_client, name="Laptop", target_amount="1000.00")
    first = await create_contribution(
        api_client,
        goal["id"],
        amount="100.00",
        occurred_on="2026-07-01",
    )
    second = await create_contribution(
        api_client,
        goal["id"],
        amount="50.00",
        occurred_on="2026-07-03",
    )
    withdrawal = await create_contribution(
        api_client,
        goal["id"],
        kind="withdrawal",
        amount="20.00",
        occurred_on="2026-07-04",
    )
    assert Decimal(first["goal_current_amount"]) == Decimal("100.00")
    assert Decimal(second["goal_current_amount"]) == Decimal("150.00")
    assert Decimal(withdrawal["goal_current_amount"]) == Decimal("130.00")
    assert Decimal(withdrawal["contribution"]["signed_amount"]) == Decimal("-20.00")

    contribution_id = first["contribution"]["id"]
    fetched = await api_client.get(
        f"/api/v1/wealth/savings-contributions/{contribution_id}"
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == contribution_id

    listed = await api_client.get(
        f"/api/v1/wealth/savings-goals/{goal['id']}/contributions",
        params={
            "start_date": "2026-07-02",
            "end_date": "2026-07-04",
            "offset": 1,
            "limit": 1,
        },
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 2
    assert listed.json()["offset"] == 1
    assert listed.json()["limit"] == 1
    assert listed.json()["items"][0]["id"] == second["contribution"]["id"]

    updated = await api_client.patch(
        f"/api/v1/wealth/savings-contributions/{contribution_id}",
        json={"amount": "120.00", "notes": "Adjusted deposit"},
    )
    assert updated.status_code == 200, updated.text
    assert Decimal(updated.json()["goal_current_amount"]) == Decimal("150.00")
    assert updated.json()["contribution"]["notes"] == "Adjusted deposit"

    overdraft = await api_client.patch(
        f"/api/v1/wealth/savings-contributions/{withdrawal['contribution']['id']}",
        json={"amount": "200.00"},
    )
    assert overdraft.status_code == 422
    unchanged = await api_client.get(
        f"/api/v1/wealth/savings-contributions/{withdrawal['contribution']['id']}"
    )
    assert Decimal(unchanged.json()["amount"]) == Decimal("20.00")

    deleted = await api_client.delete(
        f"/api/v1/wealth/savings-contributions/{contribution_id}"
    )
    assert deleted.status_code == 204
    assert (
        await api_client.get(f"/api/v1/wealth/savings-contributions/{contribution_id}")
    ).status_code == 404

    would_make_negative = await api_client.delete(
        f"/api/v1/wealth/savings-contributions/{second['contribution']['id']}"
    )
    assert would_make_negative.status_code == 409
    refreshed_goal = await api_client.get(f"/api/v1/wealth/savings-goals/{goal['id']}")
    assert Decimal(refreshed_goal.json()["current_amount"]) == Decimal("30.00")

    rejected_initial_withdrawal = await api_client.post(
        f"/api/v1/wealth/savings-goals/{uuid4()}/contributions",
        json={
            "kind": "withdrawal",
            "amount": "1.00",
            "occurred_on": "2026-07-05",
        },
    )
    assert rejected_initial_withdrawal.status_code == 404


async def test_wealth_summary_and_snapshot_crud(api_client: AsyncClient) -> None:
    await create_account(
        api_client,
        name="Checking",
        account_type="asset",
        balance="1000.00",
    )
    await create_account(
        api_client,
        name="Savings",
        account_type="asset",
        balance="500.00",
        is_savings=True,
    )
    await create_account(
        api_client,
        name="Hidden asset",
        account_type="asset",
        balance="400.00",
        include_in_net_worth=False,
    )
    await create_account(
        api_client,
        name="Credit card",
        account_type="liability",
        balance="200.00",
    )
    goal = await create_goal(
        api_client,
        name="Emergency",
        target_amount="2000.00",
    )
    await create_contribution(
        api_client,
        goal["id"],
        amount="500.00",
        occurred_on="2026-07-01",
    )

    summary = await api_client.get(
        "/api/v1/wealth/summary",
        params={"currency": "usd"},
    )
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert Decimal(body["assets"]) == Decimal("1500.00")
    assert Decimal(body["liabilities"]) == Decimal("200.00")
    assert Decimal(body["net_worth"]) == Decimal("1300.00")
    assert Decimal(body["savings"]) == Decimal("500.00")
    assert Decimal(body["savings_goal_target"]) == Decimal("2000.00")
    assert Decimal(body["savings_goal_current"]) == Decimal("500.00")

    first = await api_client.post(
        "/api/v1/wealth/net-worth-snapshots/capture",
        json={"currency": "usd", "notes": "Month end"},
    )
    assert first.status_code == 201, first.text
    snapshot = first.json()
    assert Decimal(snapshot["net_worth"]) == Decimal("1300.00")

    fetched = await api_client.get(
        f"/api/v1/wealth/net-worth-snapshots/{snapshot['id']}"
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == snapshot["id"]

    second = await api_client.post(
        "/api/v1/wealth/net-worth-snapshots/capture",
        json={"currency": "USD", "notes": "Second snapshot"},
    )
    assert second.status_code == 201
    listed = await api_client.get(
        "/api/v1/wealth/net-worth-snapshots",
        params={"currency": "usd", "offset": 1, "limit": 1},
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 2
    assert len(listed.json()["items"]) == 1

    assert (
        await api_client.post(
            "/api/v1/wealth/net-worth-snapshots/capture",
            json={
                "currency": "USD",
                "recorded_at": "2026-07-01T00:00:00+00:00",
            },
        )
    ).status_code == 422

    deleted = await api_client.delete(
        f"/api/v1/wealth/net-worth-snapshots/{snapshot['id']}"
    )
    assert deleted.status_code == 204
    assert (
        await api_client.get(f"/api/v1/wealth/net-worth-snapshots/{snapshot['id']}")
    ).status_code == 404


async def test_wealth_validation_and_missing_resources(api_client: AsyncClient) -> None:
    assert (
        await api_client.post(
            "/api/v1/wealth/accounts",
            json={
                "name": "Invalid debt savings",
                "account_type": "liability",
                "category": "loan",
                "balance": "100.00",
                "is_savings": True,
            },
        )
    ).status_code == 422
    assert (
        await api_client.get(
            "/api/v1/wealth/summary",
            params={"currency": "US1"},
        )
    ).status_code == 422

    goal = await create_goal(api_client, name="Validation goal")
    assert (
        await api_client.get(
            f"/api/v1/wealth/savings-goals/{goal['id']}/contributions",
            params={"start_date": "2026-08-01", "end_date": "2026-07-01"},
        )
    ).status_code == 422
    assert (
        await api_client.post(
            f"/api/v1/wealth/savings-goals/{goal['id']}/contributions",
            json={
                "kind": "withdrawal",
                "amount": "1.00",
                "occurred_on": "2026-07-01",
            },
        )
    ).status_code == 422

    missing_id = uuid4()
    for path in (
        f"/api/v1/wealth/accounts/{missing_id}",
        f"/api/v1/wealth/savings-goals/{missing_id}",
        f"/api/v1/wealth/net-worth-snapshots/{missing_id}",
        f"/api/v1/wealth/savings-contributions/{missing_id}",
    ):
        assert (await api_client.get(path)).status_code == 404
        assert (await api_client.delete(path)).status_code == 404
