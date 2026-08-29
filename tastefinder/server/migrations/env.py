"""
migrations/env.py
-----------------
Alembic environment.

The database URL comes from DATABASE_URL through app.config, never from
alembic.ini, so that no credential is committed and the same migrations run
against SQLite locally and PostgreSQL when deployed.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings
from app.persistence.tables import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """Resolve the URL, preferring an explicitly supplied one.

    Tests and `alembic -x url=...` pass a scratch database directly; everything
    else must supply DATABASE_URL, and require() names it loudly if unset.
    """
    override = context.get_x_argument(as_dictionary=True).get("url")
    if override:
        return str(override)
    return get_settings().require("database_url")


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite cannot ALTER most columns in place; batch mode rewrites the
        # table instead, so the same migrations run on SQLite and PostgreSQL.
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
