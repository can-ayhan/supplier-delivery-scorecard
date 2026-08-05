"""Build steps that run inside PostgreSQL."""

from __future__ import annotations

import psycopg

from scorecard.db import run_sql_file

BUILD_SCRIPTS = [
    "02_staging_clean.sql",
]


def build(conn: psycopg.Connection) -> None:
    """Run the numbered SQL scripts in order."""
    for script in BUILD_SCRIPTS:
        run_sql_file(conn, script)
    conn.commit()
