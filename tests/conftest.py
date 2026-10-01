"""Shared test configuration: which database the DB-backed tests run on.

By default every test uses a fresh in-memory SQLite database. Set
``TEST_DATABASE_URL`` to run the same tests on PostgreSQL, for example the
docker-compose one:

    TEST_DATABASE_URL=postgresql+psycopg://drivenow:drivenow@localhost:5432/drivenow_test pytest

Each test drops and recreates the tables, so the database name must end in
``_test``; anything else is refused to protect real data.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy.engine import make_url

from drivenow.db.base import Base
from drivenow.db.session import create_db_engine

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or "sqlite://"


def pytest_configure(config: pytest.Config) -> None:
    url = make_url(TEST_DATABASE_URL)
    if url.get_backend_name() != "sqlite" and not (url.database or "").endswith("_test"):
        raise pytest.UsageError(
            f"TEST_DATABASE_URL must point to a database whose name ends in '_test' (got {url.database!r}); "
            "the tests drop and recreate its tables."
        )


def pytest_report_header(config: pytest.Config) -> str:
    return f"test database: {make_url(TEST_DATABASE_URL).render_as_string(hide_password=True)}"


@pytest.fixture(scope="session")
def database_url() -> str:
    return TEST_DATABASE_URL


def reset_database(url: str) -> None:
    """Drop and recreate all tables, so a test starts empty with ids from 1."""
    engine = create_db_engine(url)
    try:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()
