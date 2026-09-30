"""Engine and session factory, built from ``DATABASE_URL``."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from drivenow.config import get_settings
from drivenow.db import models  # noqa: F401  (registers the tables on Base.metadata)
from drivenow.db.base import Base


def _is_sqlite_memory(database: str | None) -> bool:
    return database in (None, "", ":memory:")


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
    # SQLite ignores foreign keys unless this is set on every new connection.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_db_engine(url: str | None = None) -> Engine:
    """Create the SQLAlchemy engine for ``url`` (default: ``settings.database_url``).

    For SQLite this turns on foreign keys for every connection, allows use from
    FastAPI's thread pool, and shares a single connection for in-memory databases
    (``StaticPool``) so that all sessions see the same data.
    """
    database_url = make_url(url or get_settings().database_url)
    kwargs: dict[str, Any] = {}

    if database_url.get_backend_name() == "sqlite":
        kwargs["connect_args"] = {"check_same_thread": False}
        if _is_sqlite_memory(database_url.database):
            kwargs["poolclass"] = StaticPool
        engine = create_engine(database_url, **kwargs)
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
        return engine

    return create_engine(database_url, pool_pre_ping=True, **kwargs)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a session factory for ``engine``.

    ``expire_on_commit=False`` keeps the loaded attributes of returned objects,
    so they can still be read after the session is committed and closed.
    """
    return sessionmaker(bind=engine, expire_on_commit=False)


def create_tables(engine: Engine) -> None:
    """Create any missing tables, constraints and indexes. Safe to call on every startup."""
    Base.metadata.create_all(engine)
