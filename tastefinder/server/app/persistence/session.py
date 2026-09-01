"""
app/persistence/session.py
--------------------------
Engine and session construction.

The URL comes from `DATABASE_URL` through `app.config`, never from a literal
here -- the same rule `migrations/env.py` follows. SQLite locally and in
tests, PostgreSQL when deployed (`docs/01_STACK_DECISIONS.md`); the schema in
`tables.py` is written to serve both.

**SQLite does not enforce foreign keys unless asked.** `PRAGMA foreign_keys`
defaults to OFF on every new connection, so a schema full of `ForeignKey`
declarations silently enforces none of them, and tests pass against integrity
this database is not actually keeping. The listener below turns it on per
connection. PostgreSQL needs no equivalent; it has never had the option of not
enforcing them.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def build_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    """Create an engine, defaulting to the configured `DATABASE_URL`.

    `url` is an explicit override for tests and for Alembic, which knows its
    target before the application does. With neither, `require` raises and
    names the missing variable rather than failing somewhere further down.
    """
    resolved = url or get_settings().require("database_url")
    engine = create_engine(resolved, echo=echo)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    """A session factory with autoflush off.

    Autoflush hides *when* a write happens, which matters here: founding
    depends on a flush landing at a known point so an integrity error can be
    caught and translated while the transaction is still ours to roll back.
    """
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def transaction(factory: sessionmaker[Session]) -> Iterator[Session]:
    """One unit of work: commit on success, roll back on any exception.

    The atomicity founding needs (`docs/03_API_CONTRACT.md`) is this context
    manager, not anything clever inside the repositories -- a community, its
    memberships, and its aggregates either all land or none do.
    """
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
