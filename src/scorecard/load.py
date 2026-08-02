"""Land the three exports and the reference lists in the staging schema."""

from __future__ import annotations

import csv
from pathlib import Path

import psycopg

from scorecard.config import RAW_DIR, REFERENCE_DIR
from scorecard.db import run_sql_file

# export file -> landing table
EXPORTS = {
    "purchase_orders_ME2N.csv": "staging.raw_purchase_orders",
    "goods_receipts_MB51.csv": "staging.raw_goods_receipts",
    "inspection_lots_QA32.csv": "staging.raw_inspection_lots",
}
REFERENCE = {
    "plants.csv": "staging.ref_plants",
    "material_groups.csv": "staging.ref_material_groups",
    "countries.csv": "staging.ref_countries",
}


def read_export(path: Path) -> tuple[list[str], list[list[str]]]:
    """Read a semicolon separated SAP list export.

    The files are not consistently encoded: newer systems write UTF-8, the
    purchasing list still arrives in Windows-1252. Try UTF-8 first because
    it fails loudly on anything that is not UTF-8.
    """
    data = path.read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252")
    rows = list(csv.reader(text.splitlines(), delimiter=";"))
    header = [column.strip().lower() for column in rows[0]]
    return header, [row for row in rows[1:] if any(cell.strip() for cell in row)]


def _copy(conn: psycopg.Connection, table: str, columns: list[str], rows) -> int:
    count = 0
    with conn.cursor() as cur:
        with cur.copy(f"copy {table} ({', '.join(columns)}) from stdin") as copy:
            for row in rows:
                copy.write_row(row)
                count += 1
    return count


def load_exports(conn: psycopg.Connection, raw_dir: Path = RAW_DIR) -> dict[str, int]:
    run_sql_file(conn, "00_schemas.sql")
    run_sql_file(conn, "01_staging_raw.sql")

    counts: dict[str, int] = {}
    for filename, table in EXPORTS.items():
        header, rows = read_export(raw_dir / filename)
        width = len(header)
        # short rows happen when trailing empty cells are cut off
        padded = ([n, filename, *(row + [""] * width)[:width]] for n, row in enumerate(rows, start=2))
        counts[table] = _copy(conn, table, ["row_num", "source_file", *header], padded)

    for filename, table in REFERENCE.items():
        with (REFERENCE_DIR / filename).open(encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh)
            header = next(reader)
            counts[table] = _copy(conn, table, header, reader)

    conn.commit()
    return counts
