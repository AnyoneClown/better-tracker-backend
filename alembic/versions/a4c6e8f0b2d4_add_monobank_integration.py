"""add monobank integration

Revision ID: a4c6e8f0b2d4
Revises: f8b5c3d1e2a4
Create Date: 2026-07-25 23:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a4c6e8f0b2d4"
down_revision: str | Sequence[str] | None = "f8b5c3d1e2a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "monobank_connections",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("encrypted_token", sa.Text(), nullable=False),
        sa.Column("external_client_id", sa.String(length=255), nullable=False),
        sa.Column("client_name", sa.String(length=255), nullable=False),
        sa.Column("permissions", sa.String(length=100), nullable=True),
        sa.Column("client_metadata", sa.JSON(), nullable=True),
        sa.Column(
            "sync_status",
            sa.Enum(
                "idle",
                "running",
                "succeeded",
                "failed",
                name="monobank_sync_status",
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
            name=op.f("ck_monobank_connections_sync_progress_current_nonnegative"),
        ),
        sa.CheckConstraint(
            "sync_progress_total >= 0",
            name=op.f("ck_monobank_connections_sync_progress_total_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_monobank_connections_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_monobank_connections")),
        sa.UniqueConstraint("user_id", name="uq_monobank_connections_user_id"),
    )
    op.create_index(
        op.f("ix_monobank_connections_sync_status"),
        "monobank_connections",
        ["sync_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_monobank_connections_user_id"),
        "monobank_connections",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "monobank_accounts",
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("send_id", sa.String(length=255), nullable=True),
        sa.Column("card_type", sa.String(length=50), nullable=False),
        sa.Column("balance", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("credit_limit", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("masked_pan", sa.JSON(), nullable=False),
        sa.Column("iban", sa.String(length=34), nullable=True),
        sa.Column("cashback_type", sa.String(length=30), nullable=True),
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
            "credit_limit >= 0",
            name=op.f("ck_monobank_accounts_credit_limit_nonnegative"),
        ),
        sa.CheckConstraint(
            "length(currency) = 3",
            name=op.f("ck_monobank_accounts_currency_three_chars"),
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["monobank_connections.id"],
            name=op.f("fk_monobank_accounts_connection_id_monobank_connections"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_monobank_accounts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_monobank_accounts")),
        sa.UniqueConstraint(
            "user_id",
            "external_id",
            name="uq_monobank_accounts_user_external_id",
        ),
    )
    op.create_index(
        op.f("ix_monobank_accounts_connection_id"),
        "monobank_accounts",
        ["connection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_monobank_accounts_user_id"),
        "monobank_accounts",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "monobank_jars",
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("send_id", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("balance", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("goal", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
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
            "balance >= 0", name=op.f("ck_monobank_jars_balance_nonnegative")
        ),
        sa.CheckConstraint(
            "length(currency) = 3",
            name=op.f("ck_monobank_jars_currency_three_chars"),
        ),
        sa.CheckConstraint(
            "goal IS NULL OR goal >= 0",
            name=op.f("ck_monobank_jars_goal_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["monobank_connections.id"],
            name=op.f("fk_monobank_jars_connection_id_monobank_connections"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_monobank_jars_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_monobank_jars")),
        sa.UniqueConstraint(
            "user_id",
            "external_id",
            name="uq_monobank_jars_user_external_id",
        ),
    )
    op.create_index(
        op.f("ix_monobank_jars_connection_id"),
        "monobank_jars",
        ["connection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_monobank_jars_user_id"),
        "monobank_jars",
        ["user_id"],
        unique=False,
    )

    op.add_column(
        "financial_transactions",
        sa.Column(
            "source",
            sa.Enum(
                "manual",
                "monobank",
                name="financial_transaction_source",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="manual",
            nullable=False,
        ),
    )
    op.add_column(
        "financial_transactions",
        sa.Column("external_account_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "financial_transactions",
        sa.Column("external_transaction_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "financial_transactions",
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "financial_transactions", sa.Column("mcc", sa.Integer(), nullable=True)
    )
    op.add_column(
        "financial_transactions",
        sa.Column("hold", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "financial_transactions",
        sa.Column("mapped_category", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "financial_transactions",
        sa.Column("category_override", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "financial_transactions",
        sa.Column(
            "excluded_from_summary",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "financial_transactions",
        sa.Column("provider_metadata", sa.JSON(), nullable=True),
    )
    op.create_index(
        op.f("ix_financial_transactions_occurred_at"),
        "financial_transactions",
        ["occurred_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_financial_transactions_source"),
        "financial_transactions",
        ["source"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_financial_transactions_external_source",
        "financial_transactions",
        ["user_id", "source", "external_account_id", "external_transaction_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_financial_transactions_external_source",
        "financial_transactions",
        type_="unique",
    )
    op.drop_index(
        op.f("ix_financial_transactions_source"),
        table_name="financial_transactions",
    )
    op.drop_index(
        op.f("ix_financial_transactions_occurred_at"),
        table_name="financial_transactions",
    )
    for column_name in (
        "provider_metadata",
        "excluded_from_summary",
        "category_override",
        "mapped_category",
        "hold",
        "mcc",
        "occurred_at",
        "external_transaction_id",
        "external_account_id",
        "source",
    ):
        op.drop_column("financial_transactions", column_name)

    op.drop_index(op.f("ix_monobank_jars_user_id"), table_name="monobank_jars")
    op.drop_index(op.f("ix_monobank_jars_connection_id"), table_name="monobank_jars")
    op.drop_table("monobank_jars")
    op.drop_index(op.f("ix_monobank_accounts_user_id"), table_name="monobank_accounts")
    op.drop_index(
        op.f("ix_monobank_accounts_connection_id"),
        table_name="monobank_accounts",
    )
    op.drop_table("monobank_accounts")
    op.drop_index(
        op.f("ix_monobank_connections_user_id"),
        table_name="monobank_connections",
    )
    op.drop_index(
        op.f("ix_monobank_connections_sync_status"),
        table_name="monobank_connections",
    )
    op.drop_table("monobank_connections")
