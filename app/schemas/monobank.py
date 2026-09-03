from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from app.models.monobank import MonobankSyncStatus
from app.schemas.common import EntityResponse


class MonobankConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: SecretStr


class MonobankSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode="after")
    def validate_period(self) -> "MonobankSyncRequest":
        if (self.date_from is None) != (self.date_to is None):
            raise ValueError("date_from and date_to must be provided together")
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_from > self.date_to
        ):
            raise ValueError("date_from must be on or before date_to")
        return self


class MonobankAccountResponse(EntityResponse):
    external_id: str
    send_id: str | None
    card_type: str
    balance: Decimal
    credit_limit: Decimal
    currency: str
    masked_pan: list[str]
    iban: str | None
    cashback_type: str | None
    is_tracked: bool


class MonobankAccountUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_tracked: bool


class MonobankJarResponse(EntityResponse):
    external_id: str
    send_id: str | None
    title: str
    description: str | None
    balance: Decimal
    goal: Decimal | None
    currency: str
    progress_percent: Decimal | None


class MonobankConnectionResponse(BaseModel):
    connected: bool
    id: UUID | None = None
    external_client_id: str | None = None
    client_name: str | None = None
    permissions: str | None = None
    client_metadata: dict[str, Any] | None = None
    sync_status: MonobankSyncStatus | None = None
    sync_progress_current: int = 0
    sync_progress_total: int = 0
    sync_error: str | None = None
    sync_date_from: date | None = None
    sync_date_to: date | None = None
    connected_at: datetime | None = None
    last_sync_started_at: datetime | None = None
    last_sync_completed_at: datetime | None = None
    accounts: list[MonobankAccountResponse] = Field(default_factory=list)
    jars: list[MonobankJarResponse] = Field(default_factory=list)


class MonobankSyncAccepted(BaseModel):
    status: MonobankSyncStatus
    sync_progress_current: int
    sync_progress_total: int
    date_from: date
    date_to: date


class MonobankTransactionsDeleteResponse(BaseModel):
    account_id: UUID
    deleted_count: int
