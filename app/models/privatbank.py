from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PrivatBankSyncStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PrivatBankConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "privatbank_connections"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_privatbank_connections_user_id"),
        CheckConstraint(
            "sync_progress_current >= 0",
            name="sync_progress_current_nonnegative",
        ),
        CheckConstraint(
            "sync_progress_total >= 0",
            name="sync_progress_total_nonnegative",
        ),
        CheckConstraint(
            "sync_date_from IS NULL OR sync_date_to IS NULL "
            "OR sync_date_from <= sync_date_to",
            name="sync_date_range_valid",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)
    client_name: Mapped[str] = mapped_column(String(255), nullable=False)
    server_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "cockroachdb"), nullable=True
    )
    sync_status: Mapped[PrivatBankSyncStatus] = mapped_column(
        Enum(
            PrivatBankSyncStatus,
            name="privatbank_sync_status",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
        default=PrivatBankSyncStatus.IDLE,
        server_default=PrivatBankSyncStatus.IDLE.value,
        index=True,
    )
    sync_progress_current: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    sync_progress_total: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    sync_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sync_date_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    sync_date_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_sync_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_sync_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    accounts: Mapped[list["PrivatBankAccount"]] = relationship(
        back_populates="connection",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class PrivatBankAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "privatbank_accounts"
    __table_args__ = (
        CheckConstraint("length(currency) = 3", name="currency_three_chars"),
        UniqueConstraint(
            "user_id",
            "external_id",
            name="uq_privatbank_accounts_user_external_id",
        ),
    )

    connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("privatbank_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    last_movement_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    provider_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "cockroachdb"), nullable=True
    )

    connection: Mapped[PrivatBankConnection] = relationship(
        back_populates="accounts"
    )

    @property
    def masked_iban(self) -> str:
        if len(self.external_id) <= 8:
            return self.external_id
        return f"{self.external_id[:4]}••••{self.external_id[-4:]}"
