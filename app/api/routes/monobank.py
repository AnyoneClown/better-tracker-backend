from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Response, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.dependencies import CurrentUserDep, SessionDep
from app.integrations.monobank.client import (
    MonobankAPIError,
    MonobankClient,
    get_monobank_client,
)
from app.integrations.monobank.crypto import encrypt_monobank_token
from app.integrations.monobank.service import (
    KYIV_TIMEZONE,
    cancel_monobank_sync,
    connection_response,
    default_sync_period,
    schedule_monobank_sync,
    statement_time_ranges,
    synchronize_client_info,
)
from app.models.finance import FinancialTransaction, TransactionSource
from app.models.monobank import (
    MonobankAccount,
    MonobankConnection,
    MonobankJar,
    MonobankSyncStatus,
)
from app.schemas.monobank import (
    MonobankAccountResponse,
    MonobankAccountUpdate,
    MonobankConnectionCreate,
    MonobankConnectionResponse,
    MonobankJarResponse,
    MonobankSyncAccepted,
    MonobankSyncRequest,
    MonobankTransactionsDeleteResponse,
)

router = APIRouter(prefix="/integrations/monobank", tags=["monobank"])
MonobankClientDep = Annotated[MonobankClient, Depends(get_monobank_client)]


def _as_http_exception(error: MonobankAPIError) -> HTTPException:
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


@router.post("/connection", response_model=MonobankConnectionResponse)
async def connect_monobank(
    payload: MonobankConnectionCreate,
    session: SessionDep,
    current_user: CurrentUserDep,
    client: MonobankClientDep,
) -> MonobankConnectionResponse:
    token = payload.token.get_secret_value().strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Monobank token cannot be empty.",
        )
    try:
        client_info = await client.client_info(token, retry_transient=False)
    except MonobankAPIError as exc:
        raise _as_http_exception(exc) from exc

    connection = await session.scalar(
        select(MonobankConnection).where(MonobankConnection.user_id == current_user.id)
    )
    if connection is not None and connection.sync_status == MonobankSyncStatus.RUNNING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Monobank sync is already running.",
        )

    encrypted_token = encrypt_monobank_token(token)
    connected_at = datetime.now(UTC)
    if connection is None:
        connection = MonobankConnection(
            id=uuid4(),
            user_id=current_user.id,
            encrypted_token=encrypted_token,
            external_client_id="pending",
            client_name="pending",
            connected_at=connected_at,
        )
        session.add(connection)
        await session.flush()
    else:
        connection.encrypted_token = encrypted_token
        connection.connected_at = connected_at

    connection.sync_status = MonobankSyncStatus.IDLE
    connection.sync_progress_current = 0
    connection.sync_error = None
    connection.sync_date_from = None
    connection.sync_date_to = None
    connection.last_sync_started_at = None
    connection.last_sync_completed_at = None
    try:
        accounts = await synchronize_client_info(session, connection, client_info)
    except MonobankAPIError as exc:
        await session.rollback()
        raise _as_http_exception(exc) from exc
    connection.sync_progress_total = len(accounts)
    await session.commit()
    await session.refresh(connection)
    return await connection_response(session, connection)


@router.get("/connection", response_model=MonobankConnectionResponse)
async def get_monobank_connection(
    session: SessionDep,
    current_user: CurrentUserDep,
) -> MonobankConnectionResponse:
    connection = await session.scalar(
        select(MonobankConnection).where(MonobankConnection.user_id == current_user.id)
    )
    return await connection_response(session, connection)


@router.delete("/connection", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_monobank(
    session: SessionDep,
    current_user: CurrentUserDep,
) -> Response:
    connection = await session.scalar(
        select(MonobankConnection).where(MonobankConnection.user_id == current_user.id)
    )
    if connection is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    await cancel_monobank_sync(connection.id)
    await session.delete(connection)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/sync",
    response_model=MonobankSyncAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_monobank_sync(
    session: SessionDep,
    current_user: CurrentUserDep,
    client: MonobankClientDep,
    payload: Annotated[MonobankSyncRequest | None, Body()] = None,
) -> MonobankSyncAccepted:
    connection = await session.scalar(
        select(MonobankConnection).where(MonobankConnection.user_id == current_user.id)
    )
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Monobank connection not found.",
        )

    request = payload or MonobankSyncRequest()
    default_date_from, default_date_to = default_sync_period()
    date_from = request.date_from or default_date_from
    date_to = request.date_to or default_date_to
    today = datetime.now(UTC).astimezone(KYIV_TIMEZONE).date()
    if date_to > today:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="date_to cannot be in the future",
        )
    range_count = len(statement_time_ranges(date_from, date_to))

    account_count = await session.scalar(
        select(func.count())
        .select_from(MonobankAccount)
        .where(
            MonobankAccount.connection_id == connection.id,
            MonobankAccount.user_id == current_user.id,
            MonobankAccount.is_tracked.is_(True),
        )
    )
    if not account_count:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Select at least one Monobank card to track before syncing.",
        )
    started = await session.scalar(
        update(MonobankConnection)
        .where(
            MonobankConnection.id == connection.id,
            MonobankConnection.user_id == current_user.id,
            MonobankConnection.sync_status != MonobankSyncStatus.RUNNING,
        )
        .values(
            sync_status=MonobankSyncStatus.RUNNING,
            sync_progress_current=0,
            sync_progress_total=(account_count or 0) * range_count,
            sync_error=None,
            sync_date_from=date_from,
            sync_date_to=date_to,
            last_sync_started_at=datetime.now(UTC),
            last_sync_completed_at=None,
        )
        .returning(MonobankConnection.id)
    )
    if started is None:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Monobank sync is already running.",
        )
    await session.commit()

    session_factory = _background_session_factory(session)
    schedule_monobank_sync(
        connection.id,
        current_user.id,
        session_factory,
        client,
        date_from,
        date_to,
    )
    return MonobankSyncAccepted(
        status=MonobankSyncStatus.RUNNING,
        sync_progress_current=0,
        sync_progress_total=(account_count or 0) * range_count,
        date_from=date_from,
        date_to=date_to,
    )


@router.patch(
    "/accounts/{account_id}",
    response_model=MonobankAccountResponse,
)
async def update_monobank_account(
    account_id: UUID,
    payload: MonobankAccountUpdate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> MonobankAccount:
    account = await session.scalar(
        select(MonobankAccount).where(
            MonobankAccount.id == account_id,
            MonobankAccount.user_id == current_user.id,
        )
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Monobank account not found.",
        )
    connection_status = await session.scalar(
        select(MonobankConnection.sync_status).where(
            MonobankConnection.id == account.connection_id,
            MonobankConnection.user_id == current_user.id,
        )
    )
    if connection_status == MonobankSyncStatus.RUNNING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Wait for the active Monobank sync to finish before changing "
                "tracked cards."
            ),
        )

    account.is_tracked = payload.is_tracked
    await session.commit()
    await session.refresh(account)
    return account


@router.patch(
    "/jars/{jar_id}",
    response_model=MonobankJarResponse,
)
async def update_monobank_jar(
    jar_id: UUID,
    payload: MonobankAccountUpdate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> MonobankJar:
    jar = await session.scalar(
        select(MonobankJar).where(
            MonobankJar.id == jar_id,
            MonobankJar.user_id == current_user.id,
        )
    )
    if jar is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Monobank jar not found.",
        )
    connection_status = await session.scalar(
        select(MonobankConnection.sync_status).where(
            MonobankConnection.id == jar.connection_id,
            MonobankConnection.user_id == current_user.id,
        )
    )
    if connection_status == MonobankSyncStatus.RUNNING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Wait for the active Monobank sync to finish before changing "
                "tracked jars."
            ),
        )

    jar.is_tracked = payload.is_tracked
    await session.commit()
    await session.refresh(jar)
    return jar


@router.delete(
    "/accounts/{account_id}/transactions",
    response_model=MonobankTransactionsDeleteResponse,
)
async def delete_monobank_account_transactions(
    account_id: UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> MonobankTransactionsDeleteResponse:
    account = await session.scalar(
        select(MonobankAccount).where(
            MonobankAccount.id == account_id,
            MonobankAccount.user_id == current_user.id,
        )
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Monobank account not found.",
        )
    connection_status = await session.scalar(
        select(MonobankConnection.sync_status).where(
            MonobankConnection.id == account.connection_id,
            MonobankConnection.user_id == current_user.id,
        )
    )
    if connection_status == MonobankSyncStatus.RUNNING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Wait for the active Monobank sync to finish before deleting data.",
        )

    result = await session.execute(
        delete(FinancialTransaction).where(
            FinancialTransaction.user_id == current_user.id,
            FinancialTransaction.source == TransactionSource.MONOBANK,
            FinancialTransaction.external_account_id == account.external_id,
        )
    )
    deleted_count = int(getattr(result, "rowcount", 0) or 0)
    await session.commit()
    return MonobankTransactionsDeleteResponse(
        account_id=account.id,
        deleted_count=max(deleted_count, 0),
    )
