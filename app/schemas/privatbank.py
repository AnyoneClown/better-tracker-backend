from datetime import date, datetime
from decimal import Decimal
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from app.models.privatbank import PrivatBankSyncStatus
from app.schemas.common import EntityResponse


class PrivatBankConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: SecretStr


class PrivatBankSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode="after")
    def validate_period(self) -> Self:
        if (self.date_from is None) != (self.date_to is None):
            raise ValueError("date_from and date_to must be provided together")
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_from > self.date_to
        ):
            raise ValueError("date_from must be on or before date_to")
        return self


class PrivatBankAccountResponse(EntityResponse):
    external_id: str
    masked_iban: str
    name: str
    balance: Decimal
    currency: str
    last_movement_at: datetime | None


class PrivatBankConnectionResponse(BaseModel):
    connected: bool
    id: UUID | None = None
    client_name: str | None = None
    server_metadata: dict[str, Any] | None = None
    sync_status: PrivatBankSyncStatus | None = None
    sync_progress_current: int = 0
    sync_progress_total: int = 0
    sync_error: str | None = None
    sync_date_from: date | None = None
    sync_date_to: date | None = None
    connected_at: datetime | None = None
    last_sync_started_at: datetime | None = None
    last_sync_completed_at: datetime | None = None
    accounts: list[PrivatBankAccountResponse] = Field(default_factory=list)


class PrivatBankSyncAccepted(BaseModel):
    status: PrivatBankSyncStatus
    sync_progress_current: int
    sync_progress_total: int
    date_from: date
    date_to: date


class PrivatBankTransactionsDeleteResponse(BaseModel):
    account_id: UUID
    deleted_count: int
