import asyncio
from contextlib import aclosing
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import httpx
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.integrations.privatbank.client import (
    PrivatBankClient,
    get_privatbank_client,
)
from app.integrations.privatbank.service import mark_interrupted_privatbank_syncs
from app.main import app
from app.models.privatbank import PrivatBankConnection, PrivatBankSyncStatus

TOKEN_A = "privat24-business-token-a"
TOKEN_B = "privat24-business-token-b"
ACCOUNT_A = "UA123052990000026001000000001"
ACCOUNT_A_USD = "UA123052990000026001000000002"
ACCOUNT_B = "UA123052990000026001000000003"


def balance(
    account_id: str,
    *,
    name: str,
    amount: str,
    currency: str = "UAH",
) -> dict[str, Any]:
    return {
        "acc": account_id,
        "currency": currency,
        "balanceIn": amount,
        "balanceInEq": amount,
        "balanceOut": amount,
        "balanceOutEq": amount,
        "turnoverDebt": "0.00",
        "turnoverDebtEq": "0.00",
        "turnoverCred": "0.00",
        "turnoverCredEq": "0.00",
        "dpd": "26.07.2026 13:45:00",
        "nameACC": name,
        "state": "l",
        "is_final_bal": True,
    }


def transaction(
    reference: str,
    *,
    transaction_type: str,
    amount: str,
    description: str,
    state: str = "r",
) -> dict[str, Any]:
    return {
        "AUT_MY_CRF": "1234567890",
        "AUT_MY_ACC": ACCOUNT_A,
        "AUT_MY_NAM": "FOP Owner A",
        "AUT_CNTR_CRF": "0987654321",
        "AUT_CNTR_ACC": "UA000000000000000000000000000",
        "AUT_CNTR_NAM": "Counterparty",
        "CCY": "UAH",
        "FL_REAL": "r",
        "PR_PR": state,
        "DOC_TYP": "m",
        "NUM_DOC": reference,
        "DAT_KL": "25.07.2026",
        "DAT_OD": "25.07.2026",
        "OSND": description,
        "SUM": amount,
        "SUM_E": amount,
        "REF": reference,
        "REFN": "1",
        "TIM_P": "23:30",
        "DATE_TIME_DAT_OD_TIM_P": "25.07.2026 23:30:00",
        "ID": f"id-{reference}",
        "TRANTYPE": transaction_type,
        "TECHNICAL_TRANSACTION_ID": f"technical-{reference}",
    }


class ProviderState:
    def __init__(self) -> None:
        self.balances = {
            TOKEN_A: [
                balance(ACCOUNT_A, name="FOP Owner A", amount="1234.56"),
                balance(
                    ACCOUNT_A_USD,
                    name="FOP Owner A",
                    amount="-50.00",
                    currency="USD",
                ),
            ],
            TOKEN_B: [balance(ACCOUNT_B, name="FOP Owner B", amount="75.00")],
        }
        self.transactions = {
            ACCOUNT_A: [
                transaction(
                    "REF-EXPENSE",
                    transaction_type="D",
                    amount="125.40",
                    description="Business supplies",
                ),
                transaction(
                    "REF-INCOME",
                    transaction_type="C",
                    amount="1000.00",
                    description="Client payment",
                ),
            ],
            ACCOUNT_A_USD: [],
            ACCOUNT_B: [
                transaction(
                    "REF-B",
                    transaction_type="C",
                    amount="75.00",
                    description="Second owner income",
                )
            ],
        }
        self.requests: list[dict[str, Any]] = []

    async def handle(self, request: httpx.Request) -> httpx.Response:
        token = request.headers.get("token")
        self.requests.append(
            {
                "path": request.url.path,
                "params": dict(request.url.params),
                "token": token,
                "method": request.method,
            }
        )
        if token not in self.balances:
            return httpx.Response(
                401,
                json={"status": "ERROR", "code": "401", "message": "bad token"},
            )
        if request.url.path == "/api/statements/settings":
            return httpx.Response(
                200,
                json={
                    "status": "SUCCESS",
                    "type": "settings",
                    "settings": {
                        "phase": "WRK",
                        "today": "26.07.2026 00:00:00",
                        "lastday": "25.07.2026 00:00:00",
                        "server_date_time": "26.07.2026 14:00:00",
                        "date_final_statement": "25.07.2026 00:00:00",
                        "work_balance": "N",
                    },
                },
            )
        if request.url.path == "/api/statements/balance":
            provider_balances = deepcopy(self.balances[token])
            follow_id = request.url.params.get("followId")
            if len(provider_balances) > 1 and follow_id is None:
                return httpx.Response(
                    200,
                    json={
                        "status": "SUCCESS",
                        "type": "balances",
                        "exist_next_page": True,
                        "next_page_id": "balance-page-2",
                        "balances": provider_balances[:1],
                    },
                )
            return httpx.Response(
                200,
                json={
                    "status": "SUCCESS",
                    "type": "balances",
                    "exist_next_page": False,
                    "balances": provider_balances[1:]
                    if len(provider_balances) > 1
                    else provider_balances,
                },
            )
        if request.url.path == "/api/statements/transactions":
            account_id = request.url.params.get("acc", "")
            provider_transactions = deepcopy(self.transactions.get(account_id, []))
            follow_id = request.url.params.get("followId")
            if len(provider_transactions) > 1 and follow_id is None:
                return httpx.Response(
                    200,
                    json={
                        "status": "SUCCESS",
                        "type": "transactions",
                        "exist_next_page": True,
                        "next_page_id": "transaction-page-2",
                        "transactions": provider_transactions[:1],
                    },
                )
            return httpx.Response(
                200,
                json={
                    "status": "SUCCESS",
                    "type": "transactions",
                    "exist_next_page": False,
                    "transactions": provider_transactions[1:]
                    if len(provider_transactions) > 1
                    else provider_transactions,
                },
            )
        return httpx.Response(404, json={"status": "ERROR"})


async def no_sleep(_: float) -> None:
    await asyncio.sleep(0)


def install_provider(state: ProviderState) -> PrivatBankClient:
    client = PrivatBankClient(
        transport=httpx.MockTransport(state.handle),
        sleep=no_sleep,
    )
    app.dependency_overrides[get_privatbank_client] = lambda: client
    return client


async def connect(
    client: AsyncClient,
    token: str = TOKEN_A,
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/integrations/privatbank/connection",
        json={"token": token},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def wait_for_sync(
    client: AsyncClient,
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    for _ in range(500):
        response = await client.get(
            "/api/v1/integrations/privatbank/connection", headers=headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        if body["sync_status"] != "running":
            return body
        await asyncio.sleep(0.01)
    raise AssertionError("PrivatBank sync did not finish")


async def test_connect_encrypts_token_paginates_and_returns_safe_accounts(
    api_client: AsyncClient,
    sqlite_session_override: Any,
) -> None:
    state = ProviderState()
    install_provider(state)
    try:
        response = await connect(api_client)
        assert TOKEN_A not in str(response)
        assert "token" not in response
        assert response["client_name"] == "FOP Owner A"
        assert response["server_metadata"]["phase"] == "WRK"
        assert len(response["accounts"]) == 2
        assert response["accounts"][0]["masked_iban"].endswith("0001")
        assert Decimal(response["accounts"][0]["balance"]) == Decimal("1234.56")
        assert Decimal(response["accounts"][1]["balance"]) == Decimal("-50")

        async with aclosing(sqlite_session_override()) as sessions:
            session = await anext(sessions)
            connection = await session.scalar(select(PrivatBankConnection))
            assert connection is not None
            assert connection.encrypted_token != TOKEN_A
            assert TOKEN_A not in connection.encrypted_token

        provider_calls = [
            item for item in state.requests if item["path"].startswith("/api/")
        ]
        assert all(item["method"] == "GET" for item in provider_calls)
        assert any(
            item["params"].get("followId") == "balance-page-2"
            for item in provider_calls
        )

        rejected = await api_client.post(
            "/api/v1/integrations/privatbank/connection",
            json={"token": "invalid-business-token"},
        )
        assert rejected.status_code == 403
        assert "invalid-business-token" not in rejected.text
    finally:
        app.dependency_overrides.pop(get_privatbank_client, None)


async def test_sync_is_idempotent_preserves_overrides_and_refreshes_balances(
    api_client: AsyncClient,
) -> None:
    state = ProviderState()
    install_provider(state)
    try:
        connection = await connect(api_client)
        accepted = await api_client.post("/api/v1/integrations/privatbank/sync")
        assert accepted.status_code == 202, accepted.text
        accepted_body = accepted.json()
        assert date.fromisoformat(accepted_body["date_to"]) - date.fromisoformat(
            accepted_body["date_from"]
        ) == timedelta(days=30)
        assert accepted_body["sync_progress_total"] == 2

        finished = await wait_for_sync(api_client)
        assert finished["sync_status"] == "succeeded"
        assert finished["sync_progress_current"] == 2
        assert finished["sync_progress_total"] == 2
        assert any(
            item["params"].get("followId") == "transaction-page-2"
            for item in state.requests
        )

        transactions = await api_client.get(
            "/api/v1/finance/transactions?source=privatbank&limit=100"
        )
        assert transactions.status_code == 200
        assert transactions.json()["total"] == 2
        expense = next(
            item
            for item in transactions.json()["items"]
            if item["external_transaction_id"] == "REF-EXPENSE:1"
        )
        assert expense["source"] == "privatbank"
        assert expense["kind"] == "expense"
        assert Decimal(expense["amount"]) == Decimal("125.40")
        assert expense["currency"] == "UAH"
        assert expense["occurred_on"] == "2026-07-25"
        assert expense["occurred_at"].startswith("2026-07-25T20:30:00")
        assert expense["category"] == "uncategorized"
        assert expense["hold"] is False
        assert expense["provider_metadata"]["TECHNICAL_TRANSACTION_ID"].startswith(
            "technical-"
        )

        override = await api_client.patch(
            f"/api/v1/finance/transactions/{expense['id']}",
            json={"category": "Business costs", "excluded_from_summary": True},
        )
        assert override.status_code == 200, override.text
        assert (
            await api_client.patch(
                f"/api/v1/finance/transactions/{expense['id']}",
                json={"amount": "1.00"},
            )
        ).status_code == 409
        assert (
            await api_client.delete(f"/api/v1/finance/transactions/{expense['id']}")
        ).status_code == 409

        state.transactions[ACCOUNT_A][0]["SUM"] = "130.00"
        state.transactions[ACCOUNT_A][0]["PR_PR"] = "p"
        state.balances[TOKEN_A][0]["balanceOut"] = "1500.00"
        second_sync = await api_client.post(
            "/api/v1/integrations/privatbank/sync",
            json={"date_from": "2026-06-01", "date_to": "2026-07-26"},
        )
        assert second_sync.status_code == 202, second_sync.text
        await wait_for_sync(api_client)

        refreshed = await api_client.get(
            f"/api/v1/finance/transactions/{expense['id']}"
        )
        body = refreshed.json()
        assert Decimal(body["amount"]) == Decimal("130")
        assert body["hold"] is True
        assert body["category"] == "business costs"
        assert body["category_override"] == "business costs"
        assert body["excluded_from_summary"] is True
        assert (
            await api_client.get(
                "/api/v1/finance/transactions?source=privatbank&limit=100"
            )
        ).json()["total"] == 2

        summary = await api_client.get(
            "/api/v1/finance/summary?year=2026&month=7&currency=UAH"
        )
        assert Decimal(summary.json()["total_expenses"]) == 0
        assert Decimal(summary.json()["total_income"]) == Decimal("1000")
        wealth = await api_client.get("/api/v1/wealth/summary?currency=UAH")
        assert Decimal(wealth.json()["assets"]) == Decimal("1500")
        usd_wealth = await api_client.get("/api/v1/wealth/summary?currency=USD")
        assert Decimal(usd_wealth.json()["liabilities"]) == Decimal("50")
        currencies = await api_client.get("/api/v1/finance/currencies")
        assert currencies.json() == ["UAH", "USD"]

        account = next(
            item
            for item in connection["accounts"]
            if item["external_id"] == ACCOUNT_A
        )
        deleted = await api_client.delete(
            f"/api/v1/integrations/privatbank/accounts/{account['id']}/transactions"
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["deleted_count"] == 2
    finally:
        app.dependency_overrides.pop(get_privatbank_client, None)


async def test_user_isolation_conflict_interruption_and_disconnect(
    api_client: AsyncClient,
    sqlite_session_override: Any,
) -> None:
    state = ProviderState()
    install_provider(state)
    try:
        first = await connect(api_client)
        registration = await api_client.post(
            "/api/v1/auth/register",
            json={"email": "privat-second@example.com", "password": "SecondPass1!"},
        )
        assert registration.status_code == 201
        login = await api_client.post(
            "/api/v1/auth/login",
            json={"email": "privat-second@example.com", "password": "SecondPass1!"},
        )
        second_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        second = await connect(api_client, TOKEN_B, headers=second_headers)
        assert first["client_name"] == "FOP Owner A"
        assert second["client_name"] == "FOP Owner B"
        assert {item["external_id"] for item in first["accounts"]} == {
            ACCOUNT_A,
            ACCOUNT_A_USD,
        }
        assert {item["external_id"] for item in second["accounts"]} == {ACCOUNT_B}
        assert (
            await api_client.delete(
                f"/api/v1/integrations/privatbank/accounts/{first['accounts'][0]['id']}/transactions",
                headers=second_headers,
            )
        ).status_code == 404

        async with aclosing(sqlite_session_override()) as sessions:
            session: AsyncSession = await anext(sessions)
            owner_connection = await session.scalar(
                select(PrivatBankConnection).where(
                    PrivatBankConnection.client_name == "FOP Owner A"
                )
            )
            assert owner_connection is not None
            owner_connection.sync_status = PrivatBankSyncStatus.RUNNING
            await session.commit()
            assert session.bind is not None
            factory = async_sessionmaker(
                bind=session.bind,
                autoflush=False,
                expire_on_commit=False,
            )
            conflict = await api_client.post(
                "/api/v1/integrations/privatbank/sync"
            )
            assert conflict.status_code == 409
            delete_conflict = await api_client.delete(
                f"/api/v1/integrations/privatbank/accounts/{first['accounts'][0]['id']}/transactions"
            )
            assert delete_conflict.status_code == 409
            await mark_interrupted_privatbank_syncs(factory)

        interrupted = await api_client.get(
            "/api/v1/integrations/privatbank/connection"
        )
        assert interrupted.json()["sync_status"] == "failed"
        assert "interrupted" in interrupted.json()["sync_error"].lower()

        await api_client.post("/api/v1/integrations/privatbank/sync")
        await wait_for_sync(api_client)
        imported_before_disconnect = (
            await api_client.get(
                "/api/v1/finance/transactions?source=privatbank&limit=100"
            )
        ).json()["total"]
        disconnected = await api_client.delete(
            "/api/v1/integrations/privatbank/connection"
        )
        assert disconnected.status_code == 204
        disconnected_state = await api_client.get(
            "/api/v1/integrations/privatbank/connection"
        )
        assert disconnected_state.json()["connected"] is False
        remaining = await api_client.get(
            "/api/v1/finance/transactions?source=privatbank&limit=100"
        )
        assert remaining.json()["total"] == imported_before_disconnect
    finally:
        app.dependency_overrides.pop(get_privatbank_client, None)


async def test_client_retries_rate_limit_and_uses_read_only_gets() -> None:
    attempts = 0
    delays: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        assert request.method == "GET"
        assert request.headers.get("token") == TOKEN_A
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "2"}, json={})
        return httpx.Response(
            200,
            json={
                "status": "SUCCESS",
                "type": "transactions",
                "exist_next_page": False,
                "transactions": [],
            },
        )

    async def capture_sleep(delay: float) -> None:
        delays.append(delay)

    client = PrivatBankClient(
        transport=httpx.MockTransport(handler),
        sleep=capture_sleep,
    )
    result = await client.transactions(
        TOKEN_A,
        ACCOUNT_A,
        date(2026, 7, 1),
        date(2026, 7, 26),
    )
    assert result == []
    assert attempts == 2
    assert delays == [2]
