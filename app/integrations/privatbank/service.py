import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.integrations.privatbank.client import PrivatBankAPIError, PrivatBankClient
from app.integrations.privatbank.crypto import (
    PrivatBankTokenDecryptionError,
    decrypt_privatbank_token,
)
from app.models.finance import (
    FinancialTransaction,
    TransactionKind,
    TransactionSource,
)
from app.models.privatbank import (
    PrivatBankAccount,
    PrivatBankConnection,
    PrivatBankSyncStatus,
)
from app.schemas.privatbank import (
    PrivatBankAccountResponse,
    PrivatBankConnectionResponse,
)

KYIV_TIMEZONE = ZoneInfo("Europe/Kyiv")
DEFAULT_SYNC_PERIOD_DAYS = 31
DEFAULT_CATEGORY = "uncategorized"
BackgroundSessionFactory = async_sessionmaker[AsyncSession]
_sync_tasks: dict[UUID, asyncio.Task[None]] = {}


def default_sync_period(*, now: datetime | None = None) -> tuple[date, date]:
    current = (now or datetime.now(UTC)).astimezone(KYIV_TIMEZONE).date()
    return current - timedelta(days=DEFAULT_SYNC_PERIOD_DAYS - 1), current


def _required_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise PrivatBankAPIError(502, f"PrivatBank returned invalid {field} data.")
    return value.strip()


def _optional_string(payload: dict[str, Any], field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise PrivatBankAPIError(502, f"PrivatBank returned invalid {field} data.")
    normalized = value.strip()
    return normalized or None


def decimal_from_provider(value: object, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise PrivatBankAPIError(502, f"PrivatBank returned invalid {field} data.")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise PrivatBankAPIError(
            502, f"PrivatBank returned invalid {field} data."
        ) from exc
    if not amount.is_finite():
        raise PrivatBankAPIError(502, f"PrivatBank returned invalid {field} data.")
    return amount.quantize(Decimal("0.01"))


def _currency(payload: dict[str, Any], field: str = "currency") -> str:
    currency = _required_string(payload, field).upper()
    if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
        raise PrivatBankAPIError(502, f"PrivatBank returned invalid {field} data.")
    return currency


def _parse_provider_datetime(value: str, field: str) -> datetime:
    formats = (
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y",
    )
    for format_string in formats:
        try:
            parsed = datetime.strptime(value, format_string)
        except ValueError:
            continue
        return parsed.replace(tzinfo=KYIV_TIMEZONE).astimezone(UTC)
    raise PrivatBankAPIError(502, f"PrivatBank returned invalid {field} data.")


def provider_operating_date(
    settings_payload: dict[str, Any],
    *,
    now: datetime | None = None,
) -> date:
    for field in ("today", "server_date_time", "lastday"):
        value = settings_payload.get(field)
        if isinstance(value, str) and value.strip():
            return _parse_provider_datetime(value.strip(), field).astimezone(
                KYIV_TIMEZONE
            ).date()
    return (now or datetime.now(UTC)).astimezone(KYIV_TIMEZONE).date()


def safe_server_metadata(settings_payload: dict[str, Any]) -> dict[str, Any]:
    allowed_fields = (
        "phase",
        "today",
        "lastday",
        "server_date_time",
        "date_final_statement",
        "work_balance",
    )
    return {
        field: settings_payload[field]
        for field in allowed_fields
        if isinstance(settings_payload.get(field), (str, int, float, bool))
    }


def _last_movement_at(payload: dict[str, Any]) -> datetime | None:
    value = _optional_string(payload, "dpd")
    return _parse_provider_datetime(value, "dpd") if value is not None else None


async def synchronize_balances(
    session: AsyncSession,
    connection: PrivatBankConnection,
    balance_payloads: list[dict[str, Any]],
) -> list[PrivatBankAccount]:
    current_accounts = list(
        (
            await session.scalars(
                select(PrivatBankAccount).where(
                    PrivatBankAccount.connection_id == connection.id,
                    PrivatBankAccount.user_id == connection.user_id,
                )
            )
        ).all()
    )
    accounts_by_external_id = {
        account.external_id: account for account in current_accounts
    }
    payloads_by_external_id: dict[str, dict[str, Any]] = {}
    for payload in balance_payloads:
        external_id = _required_string(payload, "acc")[:255]
        payloads_by_external_id[external_id] = payload

    synchronized_accounts: list[PrivatBankAccount] = []
    for external_id, payload in payloads_by_external_id.items():
        account = accounts_by_external_id.get(external_id)
        if account is None:
            account = PrivatBankAccount(
                connection_id=connection.id,
                user_id=connection.user_id,
                external_id=external_id,
                name="PrivatBank account",
                balance=Decimal("0"),
                currency="UAH",
            )
            session.add(account)

        account.name = (
            _optional_string(payload, "nameACC") or "PrivatBank account"
        )[:255]
        account.balance = decimal_from_provider(payload.get("balanceOut"), "balanceOut")
        account.currency = _currency(payload)
        account.last_movement_at = _last_movement_at(payload)
        account.provider_metadata = dict(payload)
        synchronized_accounts.append(account)

    seen_account_ids = set(payloads_by_external_id)
    for stale_account in current_accounts:
        if stale_account.external_id not in seen_account_ids:
            await session.delete(stale_account)

    if synchronized_accounts:
        connection.client_name = synchronized_accounts[0].name
    await session.flush()
    return synchronized_accounts


async def connection_response(
    session: AsyncSession,
    connection: PrivatBankConnection | None,
) -> PrivatBankConnectionResponse:
    if connection is None:
        return PrivatBankConnectionResponse(connected=False)
    accounts = list(
        (
            await session.scalars(
                select(PrivatBankAccount)
                .where(
                    PrivatBankAccount.connection_id == connection.id,
                    PrivatBankAccount.user_id == connection.user_id,
                )
                .order_by(
                    PrivatBankAccount.currency,
                    PrivatBankAccount.name,
                    PrivatBankAccount.external_id,
                )
            )
        ).all()
    )
    return PrivatBankConnectionResponse(
        connected=True,
        id=connection.id,
        client_name=connection.client_name,
        server_metadata=connection.server_metadata,
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
            PrivatBankAccountResponse.model_validate(account) for account in accounts
        ],
    )


def _external_transaction_id(payload: dict[str, Any]) -> str:
    reference = _required_string(payload, "REF")
    reference_number = _required_string(payload, "REFN")
    return f"{reference}:{reference_number}"[:255]


def _transaction_datetime(payload: dict[str, Any]) -> datetime:
    combined = _optional_string(payload, "DATE_TIME_DAT_OD_TIM_P")
    if combined is not None:
        return _parse_provider_datetime(combined, "DATE_TIME_DAT_OD_TIM_P")
    operation_date = _required_string(payload, "DAT_OD")
    operation_time = _optional_string(payload, "TIM_P") or "00:00"
    return _parse_provider_datetime(
        f"{operation_date} {operation_time}", "DAT_OD/TIM_P"
    )


async def import_statement_items(
    session: AsyncSession,
    account: PrivatBankAccount,
    statement_items: list[dict[str, Any]],
) -> None:
    external_ids = {_external_transaction_id(item) for item in statement_items}
    existing_transactions = list(
        (
            await session.scalars(
                select(FinancialTransaction).where(
                    FinancialTransaction.user_id == account.user_id,
                    FinancialTransaction.source == TransactionSource.PRIVATBANK,
                    FinancialTransaction.external_account_id == account.external_id,
                    FinancialTransaction.external_transaction_id.in_(external_ids),
                )
            )
        ).all()
    ) if external_ids else []
    transactions_by_external_id = {
        transaction.external_transaction_id: transaction
        for transaction in existing_transactions
    }

    for statement_item in statement_items:
        external_transaction_id = _external_transaction_id(statement_item)
        transaction_type = _required_string(statement_item, "TRANTYPE").upper()
        if transaction_type not in {"C", "D"}:
            raise PrivatBankAPIError(
                502, "PrivatBank returned invalid TRANTYPE data."
            )
        amount = abs(decimal_from_provider(statement_item.get("SUM"), "SUM"))
        if amount == 0:
            continue
        occurred_at = _transaction_datetime(statement_item)
        provider_state = _required_string(statement_item, "PR_PR").casefold()
        reality_state = _optional_string(statement_item, "FL_REAL")
        is_booked = provider_state == "r" and (
            reality_state is None or reality_state.casefold() == "r"
        )

        transaction = transactions_by_external_id.get(external_transaction_id)
        if transaction is None:
            transaction = FinancialTransaction(
                user_id=account.user_id,
                source=TransactionSource.PRIVATBANK,
                external_account_id=account.external_id,
                external_transaction_id=external_transaction_id,
                kind=TransactionKind.EXPENSE,
                amount=Decimal("0.01"),
                category=DEFAULT_CATEGORY,
                occurred_on=occurred_at.astimezone(KYIV_TIMEZONE).date(),
                currency=account.currency,
            )
            session.add(transaction)
            transactions_by_external_id[external_transaction_id] = transaction

        transaction.kind = (
            TransactionKind.INCOME
            if transaction_type == "C"
            else TransactionKind.EXPENSE
        )
        transaction.amount = amount
        transaction.occurred_at = occurred_at
        transaction.occurred_on = occurred_at.astimezone(KYIV_TIMEZONE).date()
        transaction.currency = _currency(statement_item, "CCY")
        transaction.description = _optional_string(statement_item, "OSND")
        transaction.mcc = None
        transaction.hold = not is_booked
        transaction.mapped_category = DEFAULT_CATEGORY
        if transaction.category_override is None:
            transaction.category = DEFAULT_CATEGORY
        transaction.provider_metadata = dict(statement_item)


async def run_privatbank_sync(
    connection_id: UUID,
    user_id: UUID,
    session_factory: BackgroundSessionFactory,
    client: PrivatBankClient,
    date_from: date,
    date_to: date,
) -> None:
    try:
        async with session_factory() as session:
            connection = await session.scalar(
                select(PrivatBankConnection).where(
                    PrivatBankConnection.id == connection_id,
                    PrivatBankConnection.user_id == user_id,
                )
            )
            if connection is None:
                return
            token = decrypt_privatbank_token(connection.encrypted_token)

        settings_payload = await client.settings(token)
        balance_date = provider_operating_date(settings_payload)
        balance_payloads = await client.balances(token, balance_date, balance_date)
        async with session_factory() as session:
            connection = await session.scalar(
                select(PrivatBankConnection).where(
                    PrivatBankConnection.id == connection_id,
                    PrivatBankConnection.user_id == user_id,
                    PrivatBankConnection.sync_status == PrivatBankSyncStatus.RUNNING,
                )
            )
            if connection is None:
                return
            connection.server_metadata = safe_server_metadata(settings_payload)
            accounts = await synchronize_balances(
                session, connection, balance_payloads
            )
            connection.sync_progress_current = 0
            connection.sync_progress_total = len(accounts)
            await session.commit()
            account_ids = [account.id for account in accounts]

        progress = 0
        for account_id in account_ids:
            async with session_factory() as session:
                account = await session.scalar(
                    select(PrivatBankAccount).where(
                        PrivatBankAccount.id == account_id,
                        PrivatBankAccount.connection_id == connection_id,
                        PrivatBankAccount.user_id == user_id,
                    )
                )
                if account is None:
                    return
                external_account_id = account.external_id
            statement_items = await client.transactions(
                token,
                external_account_id,
                date_from,
                date_to,
            )
            async with session_factory() as session:
                account = await session.scalar(
                    select(PrivatBankAccount).where(
                        PrivatBankAccount.id == account_id,
                        PrivatBankAccount.connection_id == connection_id,
                        PrivatBankAccount.user_id == user_id,
                    )
                )
                connection = await session.scalar(
                    select(PrivatBankConnection).where(
                        PrivatBankConnection.id == connection_id,
                        PrivatBankConnection.user_id == user_id,
                        PrivatBankConnection.sync_status
                        == PrivatBankSyncStatus.RUNNING,
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
                update(PrivatBankConnection)
                .where(
                    PrivatBankConnection.id == connection_id,
                    PrivatBankConnection.user_id == user_id,
                    PrivatBankConnection.sync_status == PrivatBankSyncStatus.RUNNING,
                )
                .values(
                    sync_status=PrivatBankSyncStatus.SUCCEEDED,
                    sync_progress_current=progress,
                    sync_error=None,
                    last_sync_completed_at=datetime.now(UTC),
                )
            )
            await session.commit()
    except asyncio.CancelledError:
        raise
    except (PrivatBankAPIError, PrivatBankTokenDecryptionError) as exc:
        detail = (
            exc.detail
            if isinstance(exc, PrivatBankAPIError)
            else "Stored PrivatBank credentials could not be decrypted."
        )
        await _mark_sync_failed(session_factory, connection_id, user_id, detail)
    except Exception:
        await _mark_sync_failed(
            session_factory,
            connection_id,
            user_id,
            "PrivatBank sync failed unexpectedly.",
        )


async def _mark_sync_failed(
    session_factory: BackgroundSessionFactory,
    connection_id: UUID,
    user_id: UUID,
    detail: str,
) -> None:
    async with session_factory() as session:
        await session.execute(
            update(PrivatBankConnection)
            .where(
                PrivatBankConnection.id == connection_id,
                PrivatBankConnection.user_id == user_id,
                PrivatBankConnection.sync_status == PrivatBankSyncStatus.RUNNING,
            )
            .values(
                sync_status=PrivatBankSyncStatus.FAILED,
                sync_error=detail[:500],
                last_sync_completed_at=datetime.now(UTC),
            )
        )
        await session.commit()


def schedule_privatbank_sync(
    connection_id: UUID,
    user_id: UUID,
    session_factory: BackgroundSessionFactory,
    client: PrivatBankClient,
    date_from: date,
    date_to: date,
) -> None:
    task = asyncio.create_task(
        run_privatbank_sync(
            connection_id,
            user_id,
            session_factory,
            client,
            date_from,
            date_to,
        ),
        name=f"privatbank-sync-{connection_id}",
    )
    _sync_tasks[connection_id] = task

    def remove_finished(finished_task: asyncio.Task[None]) -> None:
        if _sync_tasks.get(connection_id) is finished_task:
            _sync_tasks.pop(connection_id, None)

    task.add_done_callback(remove_finished)


async def cancel_privatbank_sync(connection_id: UUID) -> None:
    task = _sync_tasks.pop(connection_id, None)
    if task is None or task.done():
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def cancel_all_privatbank_syncs() -> None:
    tasks = list(_sync_tasks.values())
    _sync_tasks.clear()
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def mark_interrupted_privatbank_syncs(
    session_factory: BackgroundSessionFactory,
) -> None:
    async with session_factory() as session:
        await session.execute(
            update(PrivatBankConnection)
            .where(PrivatBankConnection.sync_status == PrivatBankSyncStatus.RUNNING)
            .values(
                sync_status=PrivatBankSyncStatus.FAILED,
                sync_error="Sync interrupted by backend restart.",
                last_sync_completed_at=datetime.now(UTC),
            )
        )
        await session.commit()
