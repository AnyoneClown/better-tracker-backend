import asyncio
from contextlib import aclosing
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.integrations.monobank.client import MonobankClient, get_monobank_client
from app.integrations.monobank.mcc import category_for_mcc
from app.integrations.monobank.service import mark_interrupted_monobank_syncs
from app.main import app
from app.models.monobank import MonobankConnection, MonobankSyncStatus

TOKEN_A = "personal-token-a"
TOKEN_B = "personal-token-b"


def account(
    external_id: str,
    *,
    balance: int,
    currency_code: int = 980,
    credit_limit: int = 0,
) -> dict[str, Any]:
    return {
        "id": external_id,
        "sendId": f"send-{external_id}",
        "balance": balance,
        "creditLimit": credit_limit,
        "type": "black",
        "currencyCode": currency_code,
        "cashbackType": "UAH",
        "maskedPan": ["537541******1234"],
        "iban": "UA733220010000026201234567890",
    }


def provider_info(client_id: str, name: str, account_id: str) -> dict[str, Any]:
    return {
        "clientId": client_id,
        "name": name,
        "permissions": "psfj",
        "accounts": [account(account_id, balance=100_000, credit_limit=500_000)],
        "jars": [
            {
                "id": f"jar-{account_id}",
                "sendId": f"send-jar-{account_id}",
                "title": "Emergency fund",
                "description": "Family reserve",
                "currencyCode": 980,
                "balance": 25_000,
                "goal": 100_000,
            }
        ],
        "managedClients": [
            {
                "clientId": "business-client",
                "name": "Ignored managed client",
                "accounts": [account("managed", balance=999_999)],
            }
        ],
    }


class ProviderState:
    def __init__(self) -> None:
        first_timestamp = int(datetime(2026, 7, 25, 21, 30, tzinfo=UTC).timestamp())
        self.client_info = {
            TOKEN_A: {
                **provider_info("client-a", "Owner A", "card-a"),
                "accounts": [
                    account("card-a", balance=100_000, credit_limit=500_000),
                    account("card-debt", balance=-12_500, credit_limit=200_000),
                    account("card-usd", balance=5_000, currency_code=840),
                ],
            },
            TOKEN_B: provider_info("client-b", "Owner B", "card-b"),
        }
        self.statements: dict[str, list[dict[str, Any]]] = {
            "card-a": [
                {
                    "id": "transaction-a-expense",
                    "time": first_timestamp,
                    "description": "Night groceries",
                    "mcc": 5411,
                    "originalMcc": 5411,
                    "hold": True,
                    "amount": -12_345,
                    "operationAmount": -12_345,
                    "currencyCode": 980,
                    "balance": 87_655,
                    "counterName": "Local market",
                },
                {
                    "id": "transaction-a-income",
                    "time": first_timestamp - 3600,
                    "description": "Transfer received",
                    "mcc": 4829,
                    "hold": False,
                    "amount": 100_000,
                    "operationAmount": 100_000,
                    "currencyCode": 980,
                    "balance": 100_000,
                },
            ],
            "card-debt": [],
            "card-usd": [],
            "card-b": [
                {
                    "id": "transaction-b",
                    "time": first_timestamp,
                    "description": "Coffee",
                    "mcc": 5814,
                    "hold": False,
                    "amount": -9_900,
                    "operationAmount": -9_900,
                    "currencyCode": 980,
                    "balance": 90_100,
                }
            ],
        }
        self.calls: list[str] = []

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request.url.path)
        token = request.headers.get("X-Token")
        if token not in self.client_info:
            return httpx.Response(403, json={"errorDescription": "invalid token"})
        if request.url.path == "/personal/client-info":
            return httpx.Response(200, json=deepcopy(self.client_info[token]))
        parts = request.url.path.split("/")
        if len(parts) >= 4 and parts[1:3] == ["personal", "statement"]:
            return httpx.Response(
                200,
                json=deepcopy(self.statements.get(parts[3], [])),
            )
        return httpx.Response(404, json={})


async def no_sleep(_: float) -> None:
    await asyncio.sleep(0)


async def wait_for_sync(
    client: AsyncClient,
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    for _ in range(500):
        response = await client.get(
            "/api/v1/integrations/monobank/connection", headers=headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        if body["sync_status"] != "running":
            return body
        await asyncio.sleep(0.01)
    raise AssertionError("Monobank sync did not finish")


async def connect(
    client: AsyncClient,
    token: str = TOKEN_A,
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/integrations/monobank/connection",
        json={"token": token},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def install_provider(state: ProviderState) -> MonobankClient:
    client = MonobankClient(
        transport=httpx.MockTransport(state.handle),
        sleep=no_sleep,
        statement_delay_seconds=0,
    )
    app.dependency_overrides[get_monobank_client] = lambda: client
    return client


async def test_connect_encrypts_token_and_returns_only_safe_live_state(
    api_client: AsyncClient,
    sqlite_session_override: Any,
) -> None:
    state = ProviderState()
    install_provider(state)
    try:
        response = await connect(api_client)
        serialized = str(response)
        assert TOKEN_A not in serialized
        assert "token" not in response
        assert response["client_name"] == "Owner A"
        assert response["sync_status"] == "idle"
        assert len(response["accounts"]) == 3
        assert len(response["jars"]) == 1
        assert all(account["is_tracked"] is True for account in response["accounts"])
        assert Decimal(response["accounts"][0]["credit_limit"]) >= 0
        assert Decimal(response["jars"][0]["progress_percent"]) == Decimal("25")
        assert all(item["external_id"] != "managed" for item in response["accounts"])

        async with aclosing(sqlite_session_override()) as sessions:
            session = await anext(sessions)
            connection = await session.scalar(select(MonobankConnection))
            assert connection is not None
            assert connection.encrypted_token != TOKEN_A
            assert TOKEN_A not in connection.encrypted_token

        rejected = await api_client.post(
            "/api/v1/integrations/monobank/connection",
            json={"token": "invalid-personal-token"},
        )
        assert rejected.status_code == 403
        assert "invalid-personal-token" not in rejected.text
    finally:
        app.dependency_overrides.pop(get_monobank_client, None)


async def test_sync_imports_only_tracked_cards(
    api_client: AsyncClient,
) -> None:
    state = ProviderState()
    install_provider(state)
    try:
        connection = await connect(api_client)
        accounts = {
            account["external_id"]: account for account in connection["accounts"]
        }

        for external_id in ("card-debt", "card-usd"):
            disabled = await api_client.patch(
                f"/api/v1/integrations/monobank/accounts/{accounts[external_id]['id']}",
                json={"is_tracked": False},
            )
            assert disabled.status_code == 200, disabled.text
            assert disabled.json()["is_tracked"] is False

        refreshed = await api_client.get("/api/v1/integrations/monobank/connection")
        tracked_external_ids = {
            account["external_id"]
            for account in refreshed.json()["accounts"]
            if account["is_tracked"]
        }
        assert tracked_external_ids == {"card-a"}

        wealth = await api_client.get("/api/v1/wealth/summary?currency=UAH")
        assert Decimal(wealth.json()["assets"]) == Decimal("1250")
        assert Decimal(wealth.json()["liabilities"]) == 0
        currencies = await api_client.get("/api/v1/finance/currencies")
        assert currencies.json() == ["UAH"]

        state.calls.clear()
        accepted = await api_client.post("/api/v1/integrations/monobank/sync")
        assert accepted.status_code == 202, accepted.text
        assert accepted.json()["sync_progress_total"] == 1
        finished = await wait_for_sync(api_client)
        assert finished["sync_progress_current"] == 1
        assert finished["sync_progress_total"] == 1
        statement_calls = [
            path for path in state.calls if path.startswith("/personal/statement/")
        ]
        assert len(statement_calls) == 1
        assert statement_calls[0].startswith("/personal/statement/card-a/")

        transactions = await api_client.get(
            "/api/v1/finance/transactions?source=monobank&limit=100"
        )
        assert transactions.json()["total"] == 2

        disabled_last = await api_client.patch(
            f"/api/v1/integrations/monobank/accounts/{accounts['card-a']['id']}",
            json={"is_tracked": False},
        )
        assert disabled_last.status_code == 200
        rejected = await api_client.post("/api/v1/integrations/monobank/sync")
        assert rejected.status_code == 422
        assert "at least one" in rejected.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_monobank_client, None)


async def test_sync_is_idempotent_preserves_overrides_and_updates_provider_fields(
    api_client: AsyncClient,
) -> None:
    state = ProviderState()
    install_provider(state)
    try:
        await connect(api_client)
        accepted = await api_client.post("/api/v1/integrations/monobank/sync")
        assert accepted.status_code == 202, accepted.text
        accepted_body = accepted.json()
        assert date.fromisoformat(accepted_body["date_to"]) - date.fromisoformat(
            accepted_body["date_from"]
        ) == timedelta(days=30)
        assert accepted_body["sync_progress_total"] == 3
        finished = await wait_for_sync(api_client)
        assert finished["sync_status"] == "succeeded"
        assert finished["sync_progress_current"] == 3
        assert finished["sync_progress_total"] == 3

        transactions = await api_client.get(
            "/api/v1/finance/transactions",
            params={"currency": "UAH", "limit": 100},
        )
        assert transactions.status_code == 200
        assert transactions.json()["total"] == 2
        expense = next(
            item
            for item in transactions.json()["items"]
            if item["external_transaction_id"] == "transaction-a-expense"
        )
        assert expense["source"] == "monobank"
        assert Decimal(expense["amount"]) == Decimal("123.45")
        assert expense["kind"] == "expense"
        assert expense["category"] == "groceries"
        assert expense["occurred_on"] == "2026-07-26"
        assert expense["occurred_at"].startswith("2026-07-25T21:30:00")
        assert expense["hold"] is True
        assert expense["provider_metadata"]["counterName"] == "Local market"
        pending_summary = await api_client.get(
            "/api/v1/finance/summary?year=2026&month=7&currency=UAH"
        )
        assert Decimal(pending_summary.json()["total_expenses"]) == 0

        override = await api_client.patch(
            f"/api/v1/finance/transactions/{expense['id']}",
            json={"category": "Family Food", "excluded_from_summary": True},
        )
        assert override.status_code == 200, override.text
        immutable = await api_client.patch(
            f"/api/v1/finance/transactions/{expense['id']}",
            json={"amount": "1.00"},
        )
        assert immutable.status_code == 409
        assert (
            await api_client.delete(f"/api/v1/finance/transactions/{expense['id']}")
        ).status_code == 409

        provider_expense = state.statements["card-a"][0]
        provider_expense["operationAmount"] = -13_000
        provider_expense["amount"] = -13_000
        provider_expense["hold"] = False
        provider_expense["mcc"] = 5812
        second_sync = await api_client.post("/api/v1/integrations/monobank/sync")
        assert second_sync.status_code == 202
        await wait_for_sync(api_client)

        refreshed = await api_client.get(
            f"/api/v1/finance/transactions/{expense['id']}"
        )
        assert refreshed.status_code == 200
        body = refreshed.json()
        assert Decimal(body["amount"]) == Decimal("130.00")
        assert body["hold"] is False
        assert body["mapped_category"] == "dining"
        assert body["category"] == "family food"
        assert body["category_override"] == "family food"
        assert body["excluded_from_summary"] is True

        all_transactions = await api_client.get(
            "/api/v1/finance/transactions",
            params={"currency": "UAH", "limit": 100},
        )
        assert all_transactions.json()["total"] == 2
        summary = await api_client.get(
            "/api/v1/finance/summary?year=2026&month=7&currency=UAH"
        )
        assert Decimal(summary.json()["total_income"]) == Decimal("1000")
        assert Decimal(summary.json()["total_expenses"]) == 0

        deleted_all = await api_client.delete("/api/v1/finance/transactions")
        assert deleted_all.status_code == 200, deleted_all.text
        assert deleted_all.json() == {"deleted_count": 2}
    finally:
        app.dependency_overrides.pop(get_monobank_client, None)


async def test_sync_accepts_custom_period_and_chunks_long_ranges(
    api_client: AsyncClient,
) -> None:
    state = ProviderState()
    install_provider(state)
    try:
        await connect(api_client)
        accepted = await api_client.post(
            "/api/v1/integrations/monobank/sync",
            json={"date_from": "2026-05-01", "date_to": "2026-07-26"},
        )
        assert accepted.status_code == 202, accepted.text
        assert accepted.json() == {
            "status": "running",
            "sync_progress_current": 0,
            "sync_progress_total": 9,
            "date_from": "2026-05-01",
            "date_to": "2026-07-26",
        }

        finished = await wait_for_sync(api_client)
        assert finished["sync_status"] == "succeeded"
        assert finished["sync_progress_current"] == 9
        assert finished["sync_progress_total"] == 9
        assert finished["sync_date_from"] == "2026-05-01"
        assert finished["sync_date_to"] == "2026-07-26"

        card_calls = [
            path
            for path in state.calls
            if path.startswith("/personal/statement/card-a/")
        ]
        assert len(card_calls) == 3
        parsed_ranges = [
            tuple(map(int, path.rsplit("/", 2)[-2:])) for path in card_calls
        ]
        assert all(start <= end for start, end in parsed_ranges)
        assert all(
            end - start <= 31 * 24 * 60 * 60 + 60 * 60 for start, end in parsed_ranges
        )
        assert all(
            next_start > previous_end
            for (_, previous_end), (next_start, _) in zip(
                parsed_ranges[:-1],
                parsed_ranges[1:],
                strict=True,
            )
        )

        future = await api_client.post(
            "/api/v1/integrations/monobank/sync",
            json={"date_from": "2999-01-01", "date_to": "2999-01-31"},
        )
        assert future.status_code == 422
        incomplete = await api_client.post(
            "/api/v1/integrations/monobank/sync",
            json={"date_from": "2026-07-01"},
        )
        assert incomplete.status_code == 422
    finally:
        app.dependency_overrides.pop(get_monobank_client, None)


async def test_user_can_delete_imported_transactions_for_one_account(
    api_client: AsyncClient,
) -> None:
    state = ProviderState()
    install_provider(state)
    try:
        connection = await connect(api_client)
        card = next(
            account
            for account in connection["accounts"]
            if account["external_id"] == "card-a"
        )
        manual = await api_client.post(
            "/api/v1/finance/transactions",
            json={
                "kind": "expense",
                "amount": "5.00",
                "category": "cash",
                "occurred_on": "2026-07-26",
                "currency": "UAH",
            },
        )
        assert manual.status_code == 201

        await api_client.post("/api/v1/integrations/monobank/sync")
        await wait_for_sync(api_client)
        deleted = await api_client.delete(
            f"/api/v1/integrations/monobank/accounts/{card['id']}/transactions"
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json() == {"account_id": card["id"], "deleted_count": 2}

        remaining_monobank = await api_client.get(
            "/api/v1/finance/transactions?source=monobank&limit=100"
        )
        assert remaining_monobank.json()["total"] == 0
        remaining_all = await api_client.get(
            "/api/v1/finance/transactions?currency=UAH&limit=100"
        )
        assert remaining_all.json()["total"] == 1
        deleted_again = await api_client.delete(
            f"/api/v1/integrations/monobank/accounts/{card['id']}/transactions"
        )
        assert deleted_again.json()["deleted_count"] == 0

        registration = await api_client.post(
            "/api/v1/auth/register",
            json={"email": "mono-delete@example.com", "password": "SecondPass1!"},
        )
        assert registration.status_code == 201
        login = await api_client.post(
            "/api/v1/auth/login",
            json={"email": "mono-delete@example.com", "password": "SecondPass1!"},
        )
        second_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        isolated = await api_client.delete(
            f"/api/v1/integrations/monobank/accounts/{card['id']}/transactions",
            headers=second_headers,
        )
        assert isolated.status_code == 404
    finally:
        app.dependency_overrides.pop(get_monobank_client, None)


async def test_wealth_currencies_interruption_conflict_and_disconnect(
    api_client: AsyncClient,
    sqlite_session_override: Any,
) -> None:
    state = ProviderState()
    install_provider(state)
    try:
        await connect(api_client)
        wealth = await api_client.get("/api/v1/wealth/summary?currency=UAH")
        assert wealth.status_code == 200
        assert Decimal(wealth.json()["assets"]) == Decimal("1250")
        assert Decimal(wealth.json()["liabilities"]) == Decimal("125")
        assert Decimal(wealth.json()["savings"]) == Decimal("250")
        currencies = await api_client.get("/api/v1/finance/currencies")
        assert currencies.json() == ["UAH", "USD"]

        async with aclosing(sqlite_session_override()) as sessions:
            session: AsyncSession = await anext(sessions)
            connection = await session.scalar(select(MonobankConnection))
            assert connection is not None
            connection.sync_status = MonobankSyncStatus.RUNNING
            await session.commit()
            assert session.bind is not None
            factory = async_sessionmaker(
                bind=session.bind,
                autoflush=False,
                expire_on_commit=False,
            )
            conflict = await api_client.post("/api/v1/integrations/monobank/sync")
            assert conflict.status_code == 409
            account_id = (
                await api_client.get("/api/v1/integrations/monobank/connection")
            ).json()["accounts"][0]["id"]
            delete_conflict = await api_client.delete(
                f"/api/v1/integrations/monobank/accounts/{account_id}/transactions"
            )
            assert delete_conflict.status_code == 409
            tracking_conflict = await api_client.patch(
                f"/api/v1/integrations/monobank/accounts/{account_id}",
                json={"is_tracked": False},
            )
            assert tracking_conflict.status_code == 409
            await mark_interrupted_monobank_syncs(factory)

        interrupted = await api_client.get("/api/v1/integrations/monobank/connection")
        assert interrupted.json()["sync_status"] == "failed"
        assert "interrupted" in interrupted.json()["sync_error"].lower()

        await api_client.post("/api/v1/integrations/monobank/sync")
        await wait_for_sync(api_client)
        imported_before_disconnect = (
            await api_client.get("/api/v1/finance/transactions?source=monobank")
        ).json()["total"]
        disconnected = await api_client.delete(
            "/api/v1/integrations/monobank/connection"
        )
        assert disconnected.status_code == 204
        status_response = await api_client.get(
            "/api/v1/integrations/monobank/connection"
        )
        assert status_response.json() == {
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
        remaining = await api_client.get("/api/v1/finance/transactions?source=monobank")
        assert remaining.json()["total"] == imported_before_disconnect
        empty_wealth = await api_client.get("/api/v1/wealth/summary?currency=UAH")
        assert Decimal(empty_wealth.json()["assets"]) == 0
    finally:
        app.dependency_overrides.pop(get_monobank_client, None)


async def test_connections_and_imports_are_isolated_between_users(
    api_client: AsyncClient,
) -> None:
    state = ProviderState()
    install_provider(state)
    try:
        await connect(api_client)
        registration = await api_client.post(
            "/api/v1/auth/register",
            json={"email": "mono-second@example.com", "password": "SecondPass1!"},
        )
        assert registration.status_code == 201
        login = await api_client.post(
            "/api/v1/auth/login",
            json={"email": "mono-second@example.com", "password": "SecondPass1!"},
        )
        second_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        await connect(api_client, TOKEN_B, headers=second_headers)
        owner_connection = await api_client.get(
            "/api/v1/integrations/monobank/connection"
        )
        second_connection = await api_client.get(
            "/api/v1/integrations/monobank/connection", headers=second_headers
        )
        assert owner_connection.json()["client_name"] == "Owner A"
        assert second_connection.json()["client_name"] == "Owner B"
        assert {
            item["external_id"] for item in owner_connection.json()["accounts"]
        } == {"card-a", "card-debt", "card-usd"}
        assert {
            item["external_id"] for item in second_connection.json()["accounts"]
        } == {"card-b"}
        owner_account_id = owner_connection.json()["accounts"][0]["id"]
        hidden_tracking_update = await api_client.patch(
            f"/api/v1/integrations/monobank/accounts/{owner_account_id}",
            json={"is_tracked": False},
            headers=second_headers,
        )
        assert hidden_tracking_update.status_code == 404

        await api_client.post("/api/v1/integrations/monobank/sync")
        await wait_for_sync(api_client)
        await api_client.post(
            "/api/v1/integrations/monobank/sync", headers=second_headers
        )
        await wait_for_sync(api_client, headers=second_headers)
        owner_transactions = await api_client.get(
            "/api/v1/finance/transactions?source=monobank"
        )
        second_transactions = await api_client.get(
            "/api/v1/finance/transactions?source=monobank",
            headers=second_headers,
        )
        assert owner_transactions.json()["total"] == 2
        assert second_transactions.json()["total"] == 1
        assert (
            second_transactions.json()["items"][0]["external_transaction_id"]
            == "transaction-b"
        )
    finally:
        app.dependency_overrides.pop(get_monobank_client, None)


async def test_client_retries_rate_limits_without_exposing_credentials() -> None:
    responses = 0
    delays: list[float] = []

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal responses
        responses += 1
        if responses == 1:
            return httpx.Response(429, headers={"Retry-After": "2"}, json={})
        return httpx.Response(200, json=[])

    async def capture_sleep(delay: float) -> None:
        delays.append(delay)

    client = MonobankClient(
        transport=httpx.MockTransport(handler),
        sleep=capture_sleep,
    )
    result = await client.statement(TOKEN_A, "card-a", 1, 2)
    assert result == []
    assert responses == 2
    assert delays == [2]
    assert category_for_mcc(5411) == "groceries"
    assert category_for_mcc(9999) == "uncategorized"
