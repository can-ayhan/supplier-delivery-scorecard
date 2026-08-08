"""Build steps that run inside PostgreSQL."""

from __future__ import annotations

import psycopg

from scorecard.db import run_sql_file

BUILD_SCRIPTS = [
    "02_staging_clean.sql",
    "03_validation.sql",
    "04_star_schema.sql",
    "05_load_marts.sql",
]

MART_TABLES = [
    "dim_date", "dim_supplier", "dim_material", "dim_plant",
    "fact_po_line", "fact_goods_receipt", "fact_inspection",
]


def build(conn: psycopg.Connection) -> dict[str, int]:
    """Clean, validate and rebuild the marts. Returns row counts per mart table."""
    for script in BUILD_SCRIPTS:
        run_sql_file(conn, script)
    conn.commit()
    return {
        table: conn.execute(f"select count(*) from mart.{table}").fetchone()[0]
        for table in MART_TABLES
    }
