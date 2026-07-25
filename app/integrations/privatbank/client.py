import asyncio
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

import httpx

Sleep = Callable[[float], Awaitable[None]]


class PrivatBankAPIError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class PrivatBankClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
        retry_attempts: int = 3,
        max_pages: int = 1_000,
    ) -> None:
        self._base_url = (base_url or "https://acp.privatbank.ua").rstrip("/")
        self._transport = transport
        self._sleep = sleep
        self._retry_attempts = retry_attempts
        self._max_pages = max_pages

    async def settings(
        self,
        token: str,
        *,
        retry_transient: bool = True,
    ) -> dict[str, Any]:
        payload = await self._request(
            "/api/statements/settings",
            token,
            retry_transient=retry_transient,
        )
        settings_payload = payload.get("settings")
        if not isinstance(settings_payload, dict):
            raise PrivatBankAPIError(
                502, "PrivatBank returned invalid server settings."
            )
        return settings_payload

    async def balances(
        self,
        token: str,
        date_from: date,
        date_to: date,
        *,
        retry_transient: bool = True,
    ) -> list[dict[str, Any]]:
        return await self._paged_statement_request(
            "/api/statements/balance",
            "balances",
            token,
            date_from,
            date_to,
            retry_transient=retry_transient,
        )

    async def transactions(
        self,
        token: str,
        account_id: str,
        date_from: date,
        date_to: date,
    ) -> list[dict[str, Any]]:
        return await self._paged_statement_request(
            "/api/statements/transactions",
            "transactions",
            token,
            date_from,
            date_to,
            account_id=account_id,
            retry_transient=True,
        )

    async def _paged_statement_request(
        self,
        path: str,
        field: str,
        token: str,
        date_from: date,
        date_to: date,
        *,
        account_id: str | None = None,
        retry_transient: bool,
    ) -> list[dict[str, Any]]:
        if date_from > date_to:
            raise ValueError("date_from must be on or before date_to")

        items: list[dict[str, Any]] = []
        follow_id: str | None = None
        seen_follow_ids: set[str] = set()
        for _ in range(self._max_pages):
            params: dict[str, str | int] = {
                "startDate": date_from.strftime("%d-%m-%Y"),
                "endDate": date_to.strftime("%d-%m-%Y"),
                "limit": 100,
            }
            if account_id is not None:
                params["acc"] = account_id
            if follow_id is not None:
                params["followId"] = follow_id

            payload = await self._request(
                path,
                token,
                params=params,
                retry_transient=retry_transient,
            )
            page = payload.get(field)
            if not isinstance(page, list) or not all(
                isinstance(item, dict) for item in page
            ):
                raise PrivatBankAPIError(
                    502, f"PrivatBank returned invalid {field} data."
                )
            items.extend(page)

            has_next_page = payload.get("exist_next_page", False)
            if has_next_page is False:
                return items
            if has_next_page is not True:
                raise PrivatBankAPIError(
                    502, "PrivatBank returned invalid pagination data."
                )
            next_page_id = payload.get("next_page_id")
            if not isinstance(next_page_id, str) or not next_page_id.strip():
                raise PrivatBankAPIError(
                    502, "PrivatBank returned invalid pagination data."
                )
            follow_id = next_page_id.strip()
            if follow_id in seen_follow_ids:
                raise PrivatBankAPIError(
                    502, "PrivatBank returned repeated pagination data."
                )
            seen_follow_ids.add(follow_id)

        raise PrivatBankAPIError(502, "PrivatBank returned too many result pages.")

    async def _request(
        self,
        path: str,
        token: str,
        *,
        params: dict[str, str | int] | None = None,
        retry_transient: bool,
    ) -> dict[str, Any]:
        last_error: PrivatBankAPIError | None = None
        for attempt in range(self._retry_attempts):
            try:
                async with httpx.AsyncClient(
                    base_url=self._base_url,
                    timeout=httpx.Timeout(10.0),
                    transport=self._transport,
                    follow_redirects=False,
                ) as client:
                    response = await client.get(
                        path,
                        params=params,
                        headers={
                            "User-Agent": "BetterTracker/1.0",
                            "token": token,
                            "Accept": "application/json",
                            "Content-Type": "application/json;charset=utf-8",
                        },
                    )
            except (httpx.TimeoutException, httpx.TransportError):
                last_error = PrivatBankAPIError(
                    503, "PrivatBank is temporarily unavailable."
                )
                if retry_transient and attempt + 1 < self._retry_attempts:
                    await self._sleep(0.25 * (2**attempt))
                    continue
                raise last_error from None

            if response.status_code == 429:
                last_error = PrivatBankAPIError(
                    429, "PrivatBank rate limit reached. Try again later."
                )
                if retry_transient and attempt + 1 < self._retry_attempts:
                    await self._sleep(self._retry_after(response))
                    continue
                raise last_error
            if response.status_code in {500, 502, 503, 504}:
                last_error = PrivatBankAPIError(
                    503, "PrivatBank is temporarily unavailable."
                )
                if retry_transient and attempt + 1 < self._retry_attempts:
                    await self._sleep(0.25 * (2**attempt))
                    continue
                raise last_error
            if response.status_code == 400:
                raise PrivatBankAPIError(400, "PrivatBank rejected the request.")
            if response.status_code in {401, 403}:
                raise PrivatBankAPIError(
                    403, "PrivatBank rejected the API token or its permissions."
                )
            if not response.is_success:
                raise PrivatBankAPIError(
                    502, "PrivatBank returned an unexpected response."
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise PrivatBankAPIError(
                    502, "PrivatBank returned invalid JSON."
                ) from exc
            if not isinstance(payload, dict):
                raise PrivatBankAPIError(
                    502, "PrivatBank returned invalid response data."
                )
            provider_status = payload.get("status")
            if not isinstance(provider_status, str):
                raise PrivatBankAPIError(
                    502, "PrivatBank returned invalid response data."
                )
            if provider_status.upper() != "SUCCESS":
                raise PrivatBankAPIError(400, "PrivatBank rejected the request.")
            return payload

        if last_error is not None:
            raise last_error
        raise PrivatBankAPIError(503, "PrivatBank is temporarily unavailable.")

    @staticmethod
    def _retry_after(response: httpx.Response) -> float:
        value = response.headers.get("Retry-After")
        if value is not None:
            try:
                return max(float(value), 0)
            except ValueError:
                pass
        return 1


def get_privatbank_client() -> PrivatBankClient:
    return PrivatBankClient()
