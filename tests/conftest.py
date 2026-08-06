"""Shared fixtures.

The SQL is the thing under test, so most tests need the database from
docker-compose. They are skipped (not failed) when it is not running.
"""

from __future__ import annotations

import psycopg
import pytest

from scorecard.db import connect
from scorecard.load import load_exports
from scorecard.pipeline import build


@pytest.fixture(scope="session")
def conn():
    try:
        connection = connect()
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL is not reachable: {exc}")
    yield connection
    connection.close()


@pytest.fixture(scope="session")
def built(conn):
    """Load the committed exports and rebuild everything once per test run."""
    load_exports(conn)
    build(conn)
    return conn
