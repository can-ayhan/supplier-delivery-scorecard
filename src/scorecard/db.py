"""Thin helpers around psycopg."""

from __future__ import annotations

from pathlib import Path

import psycopg

from scorecard.config import SQL_DIR, get_settings


def connect() -> psycopg.Connection:
    return psycopg.connect(get_settings().conninfo)


def connect_reader() -> psycopg.Connection:
    """Connection for the assistant: can only read the mart schema."""
    return psycopg.connect(get_settings().reader_conninfo)


def run_sql_file(conn: psycopg.Connection, name: str) -> None:
    """Run one of the numbered scripts in sql/ as a single batch."""
    path = Path(name) if Path(name).is_absolute() else SQL_DIR / name
    conn.execute(path.read_text(encoding="utf-8"))
