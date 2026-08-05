"""Report what the validation step found."""

from __future__ import annotations

import csv
from pathlib import Path

import psycopg

SUMMARY_SQL = """
    select source, check_id, severity, handling, findings, description
    from dq.v_summary
"""

ISSUES_SQL = """
    select i.check_id, c.severity, i.source_file, i.row_num, i.record_key, i.detail
    from dq.issues i
    join dq.checks c using (check_id)
    order by c.severity, i.check_id, i.source_file, i.row_num, i.record_key
"""


def summary(conn: psycopg.Connection) -> list[tuple]:
    return conn.execute(SUMMARY_SQL).fetchall()


def print_summary(rows: list[tuple]) -> None:
    print(f"{'check':<22} {'severity':<8} {'findings':>8}  handling")
    print("-" * 62)
    source = None
    for src, check_id, severity, handling, findings, _ in rows:
        if src != source:
            source = src
            print(f"[{src}]")
        print(f"{check_id:<22} {severity:<8} {findings:>8}  {handling}")
    errors = sum(r[4] for r in rows if r[2] == "error")
    warnings = sum(r[4] for r in rows if r[2] == "warning")
    print("-" * 62)
    print(f"{errors} rows left out of the marts, {warnings} findings kept for review")


def export_issues(conn: psycopg.Connection, path: Path) -> int:
    """Write every finding to a CSV that can be sent back to purchasing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with conn.cursor() as cur, path.open("w", newline="", encoding="utf-8") as fh:
        cur.execute(ISSUES_SQL)
        writer = csv.writer(fh)
        writer.writerow([d.name for d in cur.description])
        rows = cur.fetchall()
        writer.writerows(rows)
    return len(rows)
