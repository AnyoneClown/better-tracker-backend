from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
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


class MonobankSyncStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class MonobankConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "monobank_connections"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_monobank_connections_user_id"),
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
    external_client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    client_name: Mapped[str] = mapped_column(String(255), nullable=False)
    permissions: Mapped[str | None] = mapped_column(String(100), nullable=True)
    client_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "cockroachdb"), nullable=True
    )
    sync_status: Mapped[MonobankSyncStatus] = mapped_column(
        Enum(
            MonobankSyncStatus,
            name="monobank_sync_status",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
        default=MonobankSyncStatus.IDLE,
        server_default=MonobankSyncStatus.IDLE.value,
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

    accounts: Mapped[list["MonobankAccount"]] = relationship(
        back_populates="connection",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    jars: Mapped[list["MonobankJar"]] = relationship(
        back_populates="connection",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class MonobankAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "monobank_accounts"
    __table_args__ = (
        CheckConstraint("credit_limit >= 0", name="credit_limit_nonnegative"),
        CheckConstraint("length(currency) = 3", name="currency_three_chars"),
        UniqueConstraint(
            "user_id",
            "external_id",
            name="uq_monobank_accounts_user_external_id",
        ),
    )

    connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("monobank_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    send_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    card_type: Mapped[str] = mapped_column(String(50), nullable=False)
    balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    credit_limit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    masked_pan: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB(), "cockroachdb"), nullable=False
    )
    iban: Mapped[str | None] = mapped_column(String(34), nullable=True)
    cashback_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_tracked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    connection: Mapped[MonobankConnection] = relationship(back_populates="accounts")


class MonobankJar(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "monobank_jars"
    __table_args__ = (
        CheckConstraint("balance >= 0", name="balance_nonnegative"),
        CheckConstraint("goal IS NULL OR goal >= 0", name="goal_nonnegative"),
        CheckConstraint("length(currency) = 3", name="currency_three_chars"),
        UniqueConstraint(
            "user_id",
            "external_id",
            name="uq_monobank_jars_user_external_id",
        ),
    )

    connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("monobank_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    send_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    goal: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    is_tracked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    connection: Mapped[MonobankConnection] = relationship(back_populates="jars")

    @property
    def progress_percent(self) -> Decimal | None:
        if self.goal is None or self.goal <= 0:
            return None
        return (self.balance / self.goal * 100).quantize(Decimal("0.01"))
