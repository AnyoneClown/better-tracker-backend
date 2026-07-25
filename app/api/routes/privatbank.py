from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Response, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.dependencies import CurrentUserDep, SessionDep
from app.integrations.privatbank.client import (
    PrivatBankAPIError,
    PrivatBankClient,
    get_privatbank_client,
)
from app.integrations.privatbank.crypto import encrypt_privatbank_token
from app.integrations.privatbank.service import (
    KYIV_TIMEZONE,
    cancel_privatbank_sync,
    connection_response,
    default_sync_period,
    provider_operating_date,
    safe_server_metadata,
    schedule_privatbank_sync,
    synchronize_balances,
)
from app.models.finance import FinancialTransaction, TransactionSource
from app.models.privatbank import (
    PrivatBankAccount,
    PrivatBankConnection,
    PrivatBankSyncStatus,
)
from app.schemas.privatbank import (
    PrivatBankConnectionCreate,
    PrivatBankConnectionResponse,
    PrivatBankSyncAccepted,
    PrivatBankSyncRequest,
    PrivatBankTransactionsDeleteResponse,
)

router = APIRouter(prefix="/integrations/privatbank", tags=["privatbank"])
PrivatBankClientDep = Annotated[PrivatBankClient, Depends(get_privatbank_client)]


def _as_http_exception(error: PrivatBankAPIError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.detail)


def _background_session_factory(
    session: SessionDep,
) -> async_sessionmaker[AsyncSession]:
    if session.bind is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database session is unavailable.",
        )
    return async_sessionmaker(
        bind=session.bind,
        autoflush=False,
        expire_on_commit=False,
    )


@router.post("/connection", response_model=PrivatBankConnectionResponse)
async def connect_privatbank(
    payload: PrivatBankConnectionCreate,
    session: SessionDep,
    current_user: CurrentUserDep,
    client: PrivatBankClientDep,
) -> PrivatBankConnectionResponse:
    token = payload.token.get_secret_value().strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="PrivatBank API token cannot be empty.",
        )
    try:
        settings_payload = await client.settings(token, retry_transient=False)
        balance_date = provider_operating_date(settings_payload)
        balance_payloads = await client.balances(
            token,
            balance_date,
            balance_date,
            retry_transient=False,
        )
    except PrivatBankAPIError as exc:
        raise _as_http_exception(exc) from exc

    connection = await session.scalar(
        select(PrivatBankConnection).where(
            PrivatBankConnection.user_id == current_user.id
        )
    )
    if (
        connection is not None
        and connection.sync_status == PrivatBankSyncStatus.RUNNING
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PrivatBank sync is already running.",
        )

    encrypted_token = encrypt_privatbank_token(token)
    connected_at = datetime.now(UTC)
    if connection is None:
        connection = PrivatBankConnection(
            id=uuid4(),
            user_id=current_user.id,
            encrypted_token=encrypted_token,
            client_name="PrivatBank FOP",
            connected_at=connected_at,
        )
        session.add(connection)
        await session.flush()
    else:
        connection.encrypted_token = encrypted_token
        connection.connected_at = connected_at

    connection.server_metadata = safe_server_metadata(settings_payload)
    connection.sync_status = PrivatBankSyncStatus.IDLE
    connection.sync_progress_current = 0
    connection.sync_error = None
    connection.sync_date_from = None
    connection.sync_date_to = None
    connection.last_sync_started_at = None
    connection.last_sync_completed_at = None
    try:
        accounts = await synchronize_balances(
            session, connection, balance_payloads
        )
    except PrivatBankAPIError as exc:
        await session.rollback()
        raise _as_http_exception(exc) from exc
    connection.sync_progress_total = len(accounts)
    await session.commit()
    await session.refresh(connection)
    return await connection_response(session, connection)


@router.get("/connection", response_model=PrivatBankConnectionResponse)
async def get_privatbank_connection(
    session: SessionDep,
    current_user: CurrentUserDep,
) -> PrivatBankConnectionResponse:
    connection = await session.scalar(
        select(PrivatBankConnection).where(
            PrivatBankConnection.user_id == current_user.id
        )
    )
    return await connection_response(session, connection)


@router.delete("/connection", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_privatbank(
    session: SessionDep,
    current_user: CurrentUserDep,
) -> Response:
    connection = await session.scalar(
        select(PrivatBankConnection).where(
            PrivatBankConnection.user_id == current_user.id
        )
    )
    if connection is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    await cancel_privatbank_sync(connection.id)
    await session.delete(connection)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/sync",
    response_model=PrivatBankSyncAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_privatbank_sync(
    session: SessionDep,
    current_user: CurrentUserDep,
    client: PrivatBankClientDep,
    payload: Annotated[PrivatBankSyncRequest | None, Body()] = None,
) -> PrivatBankSyncAccepted:
    connection = await session.scalar(
        select(PrivatBankConnection).where(
            PrivatBankConnection.user_id == current_user.id
        )
    )
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PrivatBank connection not found.",
        )

    request = payload or PrivatBankSyncRequest()
    default_date_from, default_date_to = default_sync_period()
    date_from = request.date_from or default_date_from
    date_to = request.date_to or default_date_to
    today = datetime.now(UTC).astimezone(KYIV_TIMEZONE).date()
    if date_to > today:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="date_to cannot be in the future",
        )

    account_count = await session.scalar(
        select(func.count())
        .select_from(PrivatBankAccount)
        .where(
            PrivatBankAccount.connection_id == connection.id,
            PrivatBankAccount.user_id == current_user.id,
        )
    )
    started = await session.scalar(
        update(PrivatBankConnection)
        .where(
            PrivatBankConnection.id == connection.id,
            PrivatBankConnection.user_id == current_user.id,
            PrivatBankConnection.sync_status != PrivatBankSyncStatus.RUNNING,
        )
        .values(
            sync_status=PrivatBankSyncStatus.RUNNING,
            sync_progress_current=0,
            sync_progress_total=account_count or 0,
            sync_error=None,
            sync_date_from=date_from,
            sync_date_to=date_to,
            last_sync_started_at=datetime.now(UTC),
            last_sync_completed_at=None,
        )
        .returning(PrivatBankConnection.id)
    )
    if started is None:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PrivatBank sync is already running.",
        )
    await session.commit()

    session_factory = _background_session_factory(session)
    schedule_privatbank_sync(
        connection.id,
        current_user.id,
        session_factory,
        client,
        date_from,
        date_to,
    )
    return PrivatBankSyncAccepted(
        status=PrivatBankSyncStatus.RUNNING,
        sync_progress_current=0,
        sync_progress_total=account_count or 0,
        date_from=date_from,
        date_to=date_to,
    )


@router.delete(
    "/accounts/{account_id}/transactions",
    response_model=PrivatBankTransactionsDeleteResponse,
)
async def delete_privatbank_account_transactions(
    account_id: UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> PrivatBankTransactionsDeleteResponse:
    account = await session.scalar(
        select(PrivatBankAccount).where(
            PrivatBankAccount.id == account_id,
            PrivatBankAccount.user_id == current_user.id,
        )
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PrivatBank account not found.",
        )
    connection_status = await session.scalar(
        select(PrivatBankConnection.sync_status).where(
            PrivatBankConnection.id == account.connection_id,
            PrivatBankConnection.user_id == current_user.id,
        )
    )
    if connection_status == PrivatBankSyncStatus.RUNNING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Wait for the active PrivatBank sync to finish before deleting data."
            ),
        )

    result = await session.execute(
        delete(FinancialTransaction).where(
            FinancialTransaction.user_id == current_user.id,
            FinancialTransaction.source == TransactionSource.PRIVATBANK,
            FinancialTransaction.external_account_id == account.external_id,
        )
    )
    deleted_count = int(getattr(result, "rowcount", 0) or 0)
    await session.commit()
    return PrivatBankTransactionsDeleteResponse(
        account_id=account.id,
        deleted_count=max(deleted_count, 0),
    )
