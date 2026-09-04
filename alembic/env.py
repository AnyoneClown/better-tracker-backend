from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import Any

from alembic.runtime.migration import MigrationContext
from sqlalchemy import Column, Connection, Index, String, Text, pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import UnaryExpression

import app.models  # noqa: F401 -- register every model with Base.metadata
from alembic import context
from app.core.config import settings
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ConfigParser treats percent signs as interpolation markers. Escaping them keeps
# percent-encoded credentials and certificate paths intact when Alembic builds
# the engine from its configuration mapping.
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

target_metadata = Base.metadata


def _has_meaningful_index_options(index: Index) -> bool:
    options = dict(index.dialect_kwargs)

    # Cockroach reflects these defaults for ordinary indexes.
    using = options.pop("postgresql_using", None)
    if using not in (None, "prefix"):
        return True

    ops = options.pop("postgresql_ops", None)
    if ops is not None and (
        not isinstance(ops, dict) or any(value is not None for value in ops.values())
    ):
        return True

    # Be conservative with partial, covering, special, and future options.
    return any(value is not None and value is not False for value in options.values())


def _plain_metadata_index_columns(
    index: Index,
) -> tuple[tuple[str | None, str, str], ...] | None:
    columns: list[tuple[str | None, str, str]] = []
    for expression in index.expressions:
        if not isinstance(expression, Column) or expression.table is None:
            return None
        columns.append(
            (expression.table.schema, expression.table.name, expression.name)
        )
    return tuple(columns)


def _reflected_crdb_default_index_columns(
    index: Index,
) -> tuple[tuple[str | None, str, str], ...] | None:
    columns: list[tuple[str | None, str, str]] = []
    for expression in index.expressions:
        if not (
            isinstance(expression, UnaryExpression)
            and expression.modifier is operators.nulls_first_op
            and isinstance(expression.element, Column)
            and expression.element.table is not None
        ):
            return None
        column = expression.element
        columns.append((column.table.schema, column.table.name, column.name))
    return tuple(columns)


def include_object(
    object_: Any,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: Any,
) -> bool:
    """Ignore Cockroach reflection differences that are not schema changes."""
    # Cockroach reflects a partial unique index as a UniqueConstraint, so the
    # same object otherwise appears once removed and once added.
    if (
        context.get_context().dialect.name == "cockroachdb"
        and name == "uq_workouts_one_active_per_user"
        and compare_to is None
        and type_ in {"index", "unique_constraint"}
    ):
        return False
    if (
        type_ != "index"
        or context.get_context().dialect.name != "cockroachdb"
        or reflected
        or not isinstance(object_, Index)
        or not isinstance(compare_to, Index)
    ):
        return True

    if bool(object_.unique) != bool(compare_to.unique):
        return True
    if _has_meaningful_index_options(object_) or _has_meaningful_index_options(
        compare_to
    ):
        return True

    metadata_columns = _plain_metadata_index_columns(object_)
    reflected_columns = _reflected_crdb_default_index_columns(compare_to)

    # Missing and extra indexes have compare_to=None, so they remain visible.
    return not (metadata_columns is not None and metadata_columns == reflected_columns)


def compare_column_type(
    migration_context: MigrationContext,
    inspected_column: Column[Any],
    metadata_column: Column[Any],
    inspected_type: Any,
    metadata_type: Any,
) -> bool | None:
    """Treat Cockroach TEXT and unbounded VARCHAR reflection as equivalent."""
    if (
        migration_context.dialect.name == "cockroachdb"
        and isinstance(metadata_type, Text)
        and isinstance(inspected_type, String)
        and inspected_type.length is None
    ):
        return False
    return None


def run_migrations_offline() -> None:
    """Run migrations without creating a database connection."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=compare_column_type,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=compare_column_type,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run Alembic operations synchronously on it."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        isolation_level="SERIALIZABLE",
    )

    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
