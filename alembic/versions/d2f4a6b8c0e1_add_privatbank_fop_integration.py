"""add privatbank fop integration

Revision ID: d2f4a6b8c0e1
Revises: b6d8f0a2c4e6
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d2f4a6b8c0e1"
down_revision: str | None = "b6d8f0a2c4e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "financial_transaction_source",
        "financial_transactions",
        type_="check",
    )
    op.alter_column(
        "financial_transactions",
        "source",
        existing_type=sa.String(length=8),
        type_=sa.String(length=10),
        existing_nullable=False,
        existing_server_default="manual",
    )
    op.create_check_constraint(
        "financial_transaction_source",
        "financial_transactions",
        "source IN ('manual', 'monobank', 'privatbank')",
    )

    op.create_table(
        "privatbank_connections",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("encrypted_token", sa.Text(), nullable=False),
        sa.Column("client_name", sa.String(length=255), nullable=False),
        sa.Column("server_metadata", sa.JSON(), nullable=True),
        sa.Column(
            "sync_status",
            sa.Enum(
                "idle",
                "running",
                "succeeded",
                "failed",
                name="privatbank_sync_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="idle",
            nullable=False,
        ),
        sa.Column(
            "sync_progress_current",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "sync_progress_total",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("sync_error", sa.String(length=500), nullable=True),
        sa.Column("sync_date_from", sa.Date(), nullable=True),
        sa.Column("sync_date_to", sa.Date(), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_sync_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sync_progress_current >= 0",
            name=op.f("ck_privatbank_connections_sync_progress_current_nonnegative"),
        ),
        sa.CheckConstraint(
            "sync_progress_total >= 0",
            name=op.f("ck_privatbank_connections_sync_progress_total_nonnegative"),
        ),
        sa.CheckConstraint(
            "sync_date_from IS NULL OR sync_date_to IS NULL "
            "OR sync_date_from <= sync_date_to",
            name=op.f("ck_privatbank_connections_sync_date_range_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_privatbank_connections_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_privatbank_connections")),
        sa.UniqueConstraint("user_id", name="uq_privatbank_connections_user_id"),
    )
    op.create_index(
        op.f("ix_privatbank_connections_sync_status"),
        "privatbank_connections",
        ["sync_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_privatbank_connections_user_id"),
        "privatbank_connections",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "privatbank_accounts",
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("balance", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("last_movement_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_metadata", sa.JSON(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(currency) = 3",
            name=op.f("ck_privatbank_accounts_currency_three_chars"),
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["privatbank_connections.id"],
            name=op.f(
                "fk_privatbank_accounts_connection_id_privatbank_connections"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_privatbank_accounts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_privatbank_accounts")),
        sa.UniqueConstraint(
            "user_id",
            "external_id",
            name="uq_privatbank_accounts_user_external_id",
        ),
    )
    op.create_index(
        op.f("ix_privatbank_accounts_connection_id"),
        "privatbank_accounts",
        ["connection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_privatbank_accounts_user_id"),
        "privatbank_accounts",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_privatbank_accounts_user_id"), table_name="privatbank_accounts"
    )
    op.drop_index(
        op.f("ix_privatbank_accounts_connection_id"),
        table_name="privatbank_accounts",
    )
    op.drop_table("privatbank_accounts")
    op.drop_index(
        op.f("ix_privatbank_connections_user_id"),
        table_name="privatbank_connections",
    )
    op.drop_index(
        op.f("ix_privatbank_connections_sync_status"),
        table_name="privatbank_connections",
    )
    op.drop_table("privatbank_connections")

    op.execute(
        sa.text("DELETE FROM financial_transactions WHERE source = 'privatbank'")
    )
    op.drop_constraint(
        "financial_transaction_source",
        "financial_transactions",
        type_="check",
    )
    op.alter_column(
        "financial_transactions",
        "source",
        existing_type=sa.String(length=10),
        type_=sa.String(length=8),
        existing_nullable=False,
        existing_server_default="manual",
    )
    op.create_check_constraint(
        "financial_transaction_source",
        "financial_transactions",
        "source IN ('manual', 'monobank')",
    )
