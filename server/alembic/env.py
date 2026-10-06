"""Alembic environment. Connection URL comes from environment or server/.env."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from app.core.local_env import load_local_env

load_local_env()

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)


def database_url() -> str:
    value = os.environ.get("PSI_DATABASE_URL")
    if not value:
        raise RuntimeError("Set PSI_DATABASE_URL before running migrations")
    parsed = make_url(value)
    if parsed.get_backend_name() != "postgresql":
        raise RuntimeError("PSI_DATABASE_URL must point to PostgreSQL")
    return value


def run_migrations_offline() -> None:
    context.configure(url=database_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url(), pool_pre_ping=True)
    with engine.connect() as connection:
        context.configure(connection=connection, transactional_ddl=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
