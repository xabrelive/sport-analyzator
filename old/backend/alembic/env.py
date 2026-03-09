"""Alembic env — run migrations with sync engine (Alembic supports sync)."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config
from sqlalchemy import pool

from app.config import settings
from app.db.base import Base
from app.models import *  # noqa: F401, F403 — register all models

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
# Use sync URL (no asyncpg) for migrations
sync_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
if sync_url == settings.database_url and "+asyncpg" in settings.database_url:
    sync_url = settings.database_url.replace("+asyncpg", "")
config.set_main_option("sqlalchemy.url", sync_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
