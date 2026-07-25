import asyncio
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.integrations.monobank.client import MonobankAPIError, MonobankClient
from app.integrations.monobank.crypto import (
    MonobankTokenDecryptionError,
    decrypt_monobank_token,
)
from app.integrations.monobank.mcc import category_for_mcc
from app.models.finance import (
    FinancialTransaction,
    TransactionKind,
    TransactionSource,
)
from app.models.monobank import (
    MonobankAccount,
    MonobankConnection,
    MonobankJar,
    MonobankSyncStatus,
)
from app.schemas.monobank import (
    MonobankAccountResponse,
    MonobankConnectionResponse,
    MonobankJarResponse,
)

KYIV_TIMEZONE = ZoneInfo("Europe/Kyiv")
DEFAULT_SYNC_PERIOD_DAYS = 31
MINOR_UNIT = Decimal("100")
ISO_4217_BY_NUMBER = {
    36: "AUD",
    124: "CAD",
    156: "CNY",
    203: "CZK",
    208: "DKK",
    348: "HUF",
    356: "INR",
    376: "ILS",
    392: "JPY",
    410: "KRW",
    498: "MDL",
    578: "NOK",
    643: "RUB",
    702: "SGD",
    752: "SEK",
    756: "CHF",
    784: "AED",
    826: "GBP",
    840: "USD",
    933: "BYN",
    944: "AZN",
    946: "RON",
    949: "TRY",
    975: "BGN",
    978: "EUR",
    980: "UAH",
    981: "GEL",
    985: "PLN",
}

BackgroundSessionFactory = async_sessionmaker[AsyncSession]
_sync_tasks: dict[UUID, asyncio.Task[None]] = {}


def default_sync_period(*, now: datetime | None = None) -> tuple[date, date]:
    current = (now or datetime.now(UTC)).astimezone(KYIV_TIMEZONE).date()
    return current - timedelta(days=DEFAULT_SYNC_PERIOD_DAYS - 1), current


def statement_time_ranges(
    date_from: date,
    date_to: date,
    *,
    now: datetime | None = None,
) -> list[tuple[int, int]]:
    """Split an inclusive Kyiv date period into Monobank-safe statement ranges."""
    if date_from > date_to:
        raise ValueError("date_from must be on or before date_to")

    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    ranges: list[tuple[int, int]] = []
    chunk_start = date_from
    while chunk_start <= date_to:
        chunk_end = min(
            chunk_start + timedelta(days=DEFAULT_SYNC_PERIOD_DAYS - 1),
            date_to,
        )
        starts_at = datetime.combine(chunk_start, time.min, tzinfo=KYIV_TIMEZONE)
        ends_at = datetime.combine(
            chunk_end + timedelta(days=1),
            time.min,
            tzinfo=KYIV_TIMEZONE,
        ) - timedelta(seconds=1)
        ends_at = min(ends_at.astimezone(UTC), current_time)
        ranges.append((int(starts_at.timestamp()), int(ends_at.timestamp())))
        chunk_start = chunk_end + timedelta(days=1)
    return ranges


def currency_from_number(value: object) -> str:
    number = _integer(value, "currencyCode")
    return ISO_4217_BY_NUMBER.get(number, "XXX")


def amount_from_minor_units(value: object) -> Decimal:
    return (Decimal(_integer(value, "amount")) / MINOR_UNIT).quantize(Decimal("0.01"))


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise MonobankAPIError(502, f"Monobank returned invalid {field} data.")
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        raise MonobankAPIError(502, f"Monobank returned invalid {field} data.")
    try:
        return int(value)
    except ValueError as exc:
        raise MonobankAPIError(502, f"Monobank returned invalid {field} data.") from exc


def _required_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise MonobankAPIError(502, f"Monobank returned invalid {field} data.")
    return value.strip()


def _optional_string(payload: dict[str, Any], field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise MonobankAPIError(502, f"Monobank returned invalid {field} data.")
    normalized = value.strip()
    return normalized or None


def _object_list(payload: dict[str, Any], field: str) -> list[dict[str, Any]]:
    value = payload.get(field, [])
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise MonobankAPIError(502, f"Monobank returned invalid {field} data.")
    return value


async def synchronize_client_info(
    session: AsyncSession,
    connection: MonobankConnection,
    payload: dict[str, Any],
) -> list[MonobankAccount]:
    connection.external_client_id = _required_string(payload, "clientId")[:255]
    connection.client_name = _required_string(payload, "name")[:255]
    connection.permissions = _optional_string(payload, "permissions")
    connection.client_metadata = {
        "clientId": connection.external_client_id,
        "name": connection.client_name,
        "permissions": connection.permissions,
    }

    account_payloads = _object_list(payload, "accounts")
    current_accounts = list(
        (
            await session.scalars(
                select(MonobankAccount).where(
                    MonobankAccount.connection_id == connection.id,
                    MonobankAccount.user_id == connection.user_id,
                )
            )
        ).all()
    )
    accounts_by_external_id = {
        account.external_id: account for account in current_accounts
    }
    seen_account_ids: set[str] = set()
    synchronized_accounts: list[MonobankAccount] = []
    for account_payload in account_payloads:
        external_id = _required_string(account_payload, "id")[:255]
        seen_account_ids.add(external_id)
        account = accounts_by_external_id.get(external_id)
        if account is None:
            account = MonobankAccount(
                connection_id=connection.id,
                user_id=connection.user_id,
                external_id=external_id,
                card_type="unknown",
                balance=Decimal("0"),
                credit_limit=Decimal("0"),
                currency="XXX",
                masked_pan=[],
            )
            session.add(account)

        masked_pan = account_payload.get("maskedPan", [])
        if not isinstance(masked_pan, list) or not all(
            isinstance(item, str) for item in masked_pan
        ):
            raise MonobankAPIError(502, "Monobank returned invalid maskedPan data.")
        account.send_id = _optional_string(account_payload, "sendId")
        account.card_type = _required_string(account_payload, "type")[:50]
        account.balance = amount_from_minor_units(account_payload.get("balance"))
        account.credit_limit = abs(
            amount_from_minor_units(account_payload.get("creditLimit", 0))
        )
        account.currency = currency_from_number(account_payload.get("currencyCode"))
        account.masked_pan = masked_pan
        account.iban = _optional_string(account_payload, "iban")
        account.cashback_type = _optional_string(account_payload, "cashbackType")
        synchronized_accounts.append(account)

    for stale_account in current_accounts:
        if stale_account.external_id not in seen_account_ids:
            await session.delete(stale_account)

    jar_payloads = _object_list(payload, "jars")
    current_jars = list(
        (
            await session.scalars(
                select(MonobankJar).where(
                    MonobankJar.connection_id == connection.id,
                    MonobankJar.user_id == connection.user_id,
                )
            )
        ).all()
    )
    jars_by_external_id = {jar.external_id: jar for jar in current_jars}
    seen_jar_ids: set[str] = set()
    for jar_payload in jar_payloads:
        external_id = _required_string(jar_payload, "id")[:255]
        seen_jar_ids.add(external_id)
        jar = jars_by_external_id.get(external_id)
        if jar is None:
            jar = MonobankJar(
                connection_id=connection.id,
                user_id=connection.user_id,
                external_id=external_id,
                title="Jar",
                balance=Decimal("0"),
                currency="XXX",
            )
            session.add(jar)
        jar.send_id = _optional_string(jar_payload, "sendId")
        jar.title = _required_string(jar_payload, "title")[:255]
        jar.description = _optional_string(jar_payload, "description")
        jar.balance = max(
            amount_from_minor_units(jar_payload.get("balance")), Decimal("0")
        )
        raw_goal = jar_payload.get("goal")
        jar.goal = (
            max(amount_from_minor_units(raw_goal), Decimal("0"))
            if raw_goal is not None
            else None
        )
        jar.currency = currency_from_number(jar_payload.get("currencyCode"))

    for stale_jar in current_jars:
        if stale_jar.external_id not in seen_jar_ids:
            await session.delete(stale_jar)

    await session.flush()
    return synchronized_accounts


async def connection_response(
    session: AsyncSession,
    connection: MonobankConnection | None,
) -> MonobankConnectionResponse:
    if connection is None:
        return MonobankConnectionResponse(connected=False)
    accounts = list(
        (
            await session.scalars(
                select(MonobankAccount)
                .where(
                    MonobankAccount.connection_id == connection.id,
                    MonobankAccount.user_id == connection.user_id,
                )
                .order_by(
                    MonobankAccount.currency,
                    MonobankAccount.card_type,
                    MonobankAccount.external_id,
                )
            )
        ).all()
    )
    jars = list(
        (
            await session.scalars(
                select(MonobankJar)
                .where(
                    MonobankJar.connection_id == connection.id,
                    MonobankJar.user_id == connection.user_id,
                )
                .order_by(
                    MonobankJar.currency,
                    MonobankJar.title,
                    MonobankJar.external_id,
                )
            )
        ).all()
    )
    return MonobankConnectionResponse(
        connected=True,
        id=connection.id,
        external_client_id=connection.external_client_id,
        client_name=connection.client_name,
        permissions=connection.permissions,
        client_metadata=connection.client_metadata,
        sync_status=connection.sync_status,
        sync_progress_current=connection.sync_progress_current,
        sync_progress_total=connection.sync_progress_total,
        sync_error=connection.sync_error,
        sync_date_from=connection.sync_date_from,
        sync_date_to=connection.sync_date_to,
        connected_at=connection.connected_at,
        last_sync_started_at=connection.last_sync_started_at,
        last_sync_completed_at=connection.last_sync_completed_at,
        accounts=[
            MonobankAccountResponse.model_validate(account) for account in accounts
        ],
        jars=[MonobankJarResponse.model_validate(jar) for jar in jars],
    )


async def import_statement_items(
    session: AsyncSession,
    account: MonobankAccount,
    statement_items: list[dict[str, Any]],
) -> None:
    external_ids = {
        item.get("id") for item in statement_items if isinstance(item.get("id"), str)
    }
    if not external_ids:
        return
    existing_transactions = list(
        (
            await session.scalars(
                select(FinancialTransaction).where(
                    FinancialTransaction.user_id == account.user_id,
                    FinancialTransaction.source == TransactionSource.MONOBANK,
                    FinancialTransaction.external_account_id == account.external_id,
                    FinancialTransaction.external_transaction_id.in_(external_ids),
                )
            )
        ).all()
    )
    transactions_by_external_id = {
        transaction.external_transaction_id: transaction
        for transaction in existing_transactions
    }

    for statement_item in statement_items:
        external_transaction_id = _required_string(statement_item, "id")[:255]
        timestamp = _integer(statement_item.get("time"), "time")
        occurred_at = datetime.fromtimestamp(timestamp, UTC)
        operation_value = statement_item.get(
            "operationAmount", statement_item.get("amount")
        )
        signed_amount = amount_from_minor_units(operation_value)
        if signed_amount == 0:
            continue
        raw_mcc = statement_item.get("mcc")
        mcc = _integer(raw_mcc, "mcc") if raw_mcc is not None else None
        mapped_category = category_for_mcc(mcc)
        transaction = transactions_by_external_id.get(external_transaction_id)
        if transaction is None:
            transaction = FinancialTransaction(
                user_id=account.user_id,
                source=TransactionSource.MONOBANK,
                external_account_id=account.external_id,
                external_transaction_id=external_transaction_id,
                kind=TransactionKind.EXPENSE,
                amount=Decimal("0.01"),
                category=mapped_category,
                occurred_on=occurred_at.astimezone(KYIV_TIMEZONE).date(),
                currency=account.currency,
            )
            session.add(transaction)
            transactions_by_external_id[external_transaction_id] = transaction

        transaction.kind = (
            TransactionKind.INCOME if signed_amount > 0 else TransactionKind.EXPENSE
        )
        transaction.amount = abs(signed_amount)
        transaction.occurred_at = occurred_at
        transaction.occurred_on = occurred_at.astimezone(KYIV_TIMEZONE).date()
        currency_code = statement_item.get("currencyCode")
        transaction.currency = (
            currency_from_number(currency_code)
            if currency_code is not None
            else account.currency
        )
        transaction.description = _optional_string(statement_item, "description")
        transaction.mcc = mcc
        transaction.hold = bool(statement_item.get("hold", False))
        transaction.mapped_category = mapped_category
        if transaction.category_override is None:
            transaction.category = mapped_category
        transaction.provider_metadata = dict(statement_item)


async def run_monobank_sync(
    connection_id: UUID,
    user_id: UUID,
    session_factory: BackgroundSessionFactory,
    client: MonobankClient,
    date_from: date,
    date_to: date,
) -> None:
    try:
        async with session_factory() as session:
            connection = await session.scalar(
                select(MonobankConnection).where(
                    MonobankConnection.id == connection_id,
                    MonobankConnection.user_id == user_id,
                )
            )
            if connection is None:
                return
            token = decrypt_monobank_token(connection.encrypted_token)

        client_info = await client.client_info(token, retry_rate_limit=True)
        async with session_factory() as session:
            connection = await session.scalar(
                select(MonobankConnection).where(
                    MonobankConnection.id == connection_id,
                    MonobankConnection.user_id == user_id,
                    MonobankConnection.sync_status == MonobankSyncStatus.RUNNING,
                )
            )
            if connection is None:
                return
            accounts = await synchronize_client_info(session, connection, client_info)
            connection.sync_progress_current = 0
            statement_ranges = statement_time_ranges(date_from, date_to)
            connection.sync_progress_total = len(accounts) * len(statement_ranges)
            await session.commit()
            account_ids = [account.id for account in accounts]

        progress = 0
        statement_request_index = 0
        for account_id in account_ids:
            async with session_factory() as session:
                account = await session.scalar(
                    select(MonobankAccount).where(
                        MonobankAccount.id == account_id,
                        MonobankAccount.connection_id == connection_id,
                        MonobankAccount.user_id == user_id,
                    )
                )
                if account is None:
                    return
                external_account_id = account.external_id
            for timestamp_from, timestamp_to in statement_ranges:
                if statement_request_index > 0:
                    await client.wait_between_statements()
                statement_request_index += 1
                statement_items = await client.statement(
                    token,
                    external_account_id,
                    timestamp_from,
                    timestamp_to,
                )
                async with session_factory() as session:
                    account = await session.scalar(
                        select(MonobankAccount).where(
                            MonobankAccount.id == account_id,
                            MonobankAccount.connection_id == connection_id,
                            MonobankAccount.user_id == user_id,
                        )
                    )
                    connection = await session.scalar(
                        select(MonobankConnection).where(
                            MonobankConnection.id == connection_id,
                            MonobankConnection.user_id == user_id,
                            MonobankConnection.sync_status
                            == MonobankSyncStatus.RUNNING,
                        )
                    )
                    if account is None or connection is None:
                        return
                    await import_statement_items(session, account, statement_items)
                    progress += 1
                    connection.sync_progress_current = progress
                    await session.commit()

        async with session_factory() as session:
            await session.execute(
                update(MonobankConnection)
                .where(
                    MonobankConnection.id == connection_id,
                    MonobankConnection.user_id == user_id,
                    MonobankConnection.sync_status == MonobankSyncStatus.RUNNING,
                )
                .values(
                    sync_status=MonobankSyncStatus.SUCCEEDED,
                    sync_error=None,
                    last_sync_completed_at=datetime.now(UTC),
                )
            )
            await session.commit()
    except asyncio.CancelledError:
        raise
    except (MonobankAPIError, MonobankTokenDecryptionError) as exc:
        detail = (
            exc.detail
            if isinstance(exc, MonobankAPIError)
            else "Stored Monobank credentials could not be decrypted."
        )
        await _mark_sync_failed(session_factory, connection_id, user_id, detail)
    except Exception:
        await _mark_sync_failed(
            session_factory,
            connection_id,
            user_id,
            "Monobank sync failed unexpectedly.",
        )


async def _mark_sync_failed(
    session_factory: BackgroundSessionFactory,
    connection_id: UUID,
    user_id: UUID,
    detail: str,
) -> None:
    async with session_factory() as session:
        await session.execute(
            update(MonobankConnection)
            .where(
                MonobankConnection.id == connection_id,
                MonobankConnection.user_id == user_id,
                MonobankConnection.sync_status == MonobankSyncStatus.RUNNING,
            )
            .values(
                sync_status=MonobankSyncStatus.FAILED,
                sync_error=detail[:500],
                last_sync_completed_at=datetime.now(UTC),
            )
        )
        await session.commit()


def schedule_monobank_sync(
    connection_id: UUID,
    user_id: UUID,
    session_factory: BackgroundSessionFactory,
    client: MonobankClient,
    date_from: date,
    date_to: date,
) -> None:
    task = asyncio.create_task(
        run_monobank_sync(
            connection_id,
            user_id,
            session_factory,
            client,
            date_from,
            date_to,
        ),
        name=f"monobank-sync-{connection_id}",
    )
    _sync_tasks[connection_id] = task

    def remove_finished(finished_task: asyncio.Task[None]) -> None:
        if _sync_tasks.get(connection_id) is finished_task:
            _sync_tasks.pop(connection_id, None)

    task.add_done_callback(remove_finished)


async def cancel_monobank_sync(connection_id: UUID) -> None:
    task = _sync_tasks.pop(connection_id, None)
    if task is None or task.done():
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def cancel_all_monobank_syncs() -> None:
    tasks = list(_sync_tasks.values())
    _sync_tasks.clear()
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def mark_interrupted_monobank_syncs(
    session_factory: BackgroundSessionFactory,
) -> None:
    async with session_factory() as session:
        await session.execute(
            update(MonobankConnection)
            .where(MonobankConnection.sync_status == MonobankSyncStatus.RUNNING)
            .values(
                sync_status=MonobankSyncStatus.FAILED,
                sync_error="Sync interrupted by backend restart.",
                last_sync_completed_at=datetime.now(UTC),
            )
        )
        await session.commit()
