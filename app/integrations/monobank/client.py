import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

Sleep = Callable[[float], Awaitable[None]]


class MonobankAPIError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class MonobankClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
        retry_attempts: int = 3,
        statement_delay_seconds: float = 61,
    ) -> None:
        self._base_url = (base_url or "https://api.monobank.ua").rstrip("/")
        self._transport = transport
        self._sleep = sleep
        self._retry_attempts = retry_attempts
        self._statement_delay_seconds = statement_delay_seconds

    async def client_info(
        self,
        token: str,
        *,
        retry_rate_limit: bool = False,
        retry_transient: bool = True,
    ) -> dict[str, Any]:
        payload = await self._request(
            "/personal/client-info",
            token,
            retry_rate_limit=retry_rate_limit,
            retry_transient=retry_transient,
        )
        if not isinstance(payload, dict):
            raise MonobankAPIError(502, "Monobank returned invalid client data.")
        return payload

    async def statement(
        self,
        token: str,
        account_id: str,
        timestamp_from: int,
        timestamp_to: int,
    ) -> list[dict[str, Any]]:
        payload = await self._request(
            f"/personal/statement/{account_id}/{timestamp_from}/{timestamp_to}",
            token,
            retry_rate_limit=True,
            retry_transient=True,
        )
        if not isinstance(payload, list) or not all(
            isinstance(item, dict) for item in payload
        ):
            raise MonobankAPIError(502, "Monobank returned an invalid statement.")
        return payload

    async def wait_between_statements(self) -> None:
        await self._sleep(self._statement_delay_seconds)

    async def _request(
        self,
        path: str,
        token: str,
        *,
        retry_rate_limit: bool,
        retry_transient: bool,
    ) -> Any:
        last_error: MonobankAPIError | None = None
        for attempt in range(self._retry_attempts):
            try:
                async with httpx.AsyncClient(
                    base_url=self._base_url,
                    timeout=httpx.Timeout(10.0),
                    transport=self._transport,
                    follow_redirects=False,
                ) as client:
                    response = await client.get(path, headers={"X-Token": token})
            except (httpx.TimeoutException, httpx.TransportError):
                last_error = MonobankAPIError(
                    503, "Monobank is temporarily unavailable."
                )
                if retry_transient and attempt + 1 < self._retry_attempts:
                    await self._sleep(0.25 * (2**attempt))
                    continue
                raise last_error from None

            if response.status_code == 429:
                last_error = MonobankAPIError(
                    429, "Monobank rate limit reached. Try again later."
                )
                if retry_rate_limit and attempt + 1 < self._retry_attempts:
                    await self._sleep(self._retry_after(response))
                    continue
                raise last_error
            if response.status_code >= 500:
                last_error = MonobankAPIError(
                    503, "Monobank is temporarily unavailable."
                )
                if retry_transient and attempt + 1 < self._retry_attempts:
                    await self._sleep(0.25 * (2**attempt))
                    continue
                raise last_error
            if response.status_code == 400:
                raise MonobankAPIError(400, "Monobank rejected the request.")
            if response.status_code == 403:
                raise MonobankAPIError(403, "Monobank rejected the access token.")
            if not response.is_success:
                raise MonobankAPIError(502, "Monobank returned an unexpected response.")
            try:
                return response.json()
            except ValueError as exc:
                raise MonobankAPIError(502, "Monobank returned invalid JSON.") from exc

        if last_error is not None:
            raise last_error
        raise MonobankAPIError(503, "Monobank is temporarily unavailable.")

    @staticmethod
    def _retry_after(response: httpx.Response) -> float:
        value = response.headers.get("Retry-After")
        if value is not None:
            try:
                return max(float(value), 0)
            except ValueError:
                pass
        return 61


def get_monobank_client() -> MonobankClient:
    return MonobankClient()
