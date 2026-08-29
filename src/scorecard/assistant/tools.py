"""The three tools the assistant can call. All of them only read."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import psycopg

from scorecard.assistant.guard import ALLOWED_TABLES, MAX_ROWS, SCHEMA, QueryRejected, check

TABLE_NOTES = {
    "v_supplier_scorecard": "One row per supplier with the finished KPIs, scores and rank over the whole period. Start here for supplier comparisons.",
    "v_delivery_lines": "One row per PO line, already joined to supplier, material, plant and dates. Flags are 0/1 (due_lines, on_time_lines, in_full_lines, otif_lines) so rates are sum(flag) / sum(due_lines).",
    "v_supplier_month": "Supplier by month: delivery KPIs by due month, defect rate by inspection month.",
    "fact_po_line": "One row per purchase order line with ordered and received quantity, lead time, days late and the is_due / is_on_time / is_in_full / is_otif flags.",
    "fact_goods_receipt": "One row per material document line. movement_type 101 = receipt, 102 = reversal, 122 = return to supplier. Quantity is signed.",
    "fact_inspection": "One row per inspection lot: lot, accepted and rejected quantity, usage decision.",
    "dim_supplier": "Supplier name, country and region (Domestic / EU / Non-EU).",
    "dim_material": "Material, material group and base unit.",
    "dim_plant": "Receiving plant.",
    "dim_date": "Calendar. Facts join on the integer date_key (yyyymmdd).",
    "kpi_params": "One row: tolerances, score weights, OTIF target and the as-of date of the data.",
}

def _tool(name: str, description: str, properties: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": list(properties),
                           "additionalProperties": False},
        },
    }


TOOL_DEFINITIONS = [
    _tool("list_tables",
          "List the tables and views you can query, with what each one contains. Call this first if you have not "
          "seen the schema in this conversation.", {}),
    _tool("describe_table",
          "Show the columns and types of one table or view, and the distinct values of its low-cardinality text "
          "columns. Call this before writing SQL against a table so column names and status values are exact.",
          {"table": {"type": "string", "description": "Table or view name without schema, for example v_delivery_lines."}}),
    _tool("run_query",
          f"Run one read-only PostgreSQL SELECT against the {SCHEMA} schema and get the rows back. Results are capped "
          f"at {MAX_ROWS} rows, so aggregate in SQL instead of fetching detail rows. A rejected or failing query "
          "returns the reason so you can fix it.",
          {"sql": {"type": "string", "description": "A single SELECT statement."}}),
]


class ToolError(Exception):
    """Something the model can recover from; returned to it as an error result."""


def _plain(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


def list_tables(conn: psycopg.Connection) -> list[dict]:
    rows = conn.execute(
        """select c.relname, case c.relkind when 'v' then 'view' else 'table' end
           from pg_class c join pg_namespace n on n.oid = c.relnamespace
           where n.nspname = %s and c.relkind in ('r', 'v') and c.relname = any(%s)
           order by c.relkind desc, c.relname""",
        [SCHEMA, sorted(ALLOWED_TABLES)],
    ).fetchall()
    return [{"table": name, "kind": kind, "contains": TABLE_NOTES.get(name, "")} for name, kind in rows]


def describe_table(conn: psycopg.Connection, table: str) -> dict:
    name = table.lower().removeprefix(f"{SCHEMA}.")
    if name not in ALLOWED_TABLES:
        raise ToolError(f"Unknown table {table!r}. Call list_tables to see what is available.")
    columns = conn.execute(
        """select column_name, data_type from information_schema.columns
           where table_schema = %s and table_name = %s order by ordinal_position""",
        [SCHEMA, name],
    ).fetchall()
    described = []
    for column, data_type in columns:
        entry = {"column": column, "type": data_type}
        if data_type == "text":
            values = [r[0] for r in conn.execute(
                psycopg.sql.SQL("select distinct {} from {}.{} where {} is not null order by 1 limit 16").format(
                    psycopg.sql.Identifier(column), psycopg.sql.Identifier(SCHEMA),
                    psycopg.sql.Identifier(name), psycopg.sql.Identifier(column),
                )
            )]
            if len(values) <= 15:
                entry["values"] = values
        described.append(entry)
    return {"table": name, "contains": TABLE_NOTES.get(name, ""), "columns": described}


def run_query(conn: psycopg.Connection, sql: str) -> dict:
    try:
        safe_sql = check(sql)
    except QueryRejected as exc:
        raise ToolError(str(exc)) from exc
    try:
        with conn.cursor() as cur:
            cur.execute(safe_sql)
            columns = [d.name for d in cur.description]
            rows = [[_plain(v) for v in row] for row in cur.fetchall()]
    except psycopg.Error as exc:
        conn.rollback()
        raise ToolError(f"PostgreSQL error: {exc.diag.message_primary or exc}") from exc
    conn.rollback()   # nothing to keep; also releases the snapshot
    return {"sql": safe_sql, "columns": columns, "rows": rows, "row_count": len(rows)}


def call(conn: psycopg.Connection, name: str, arguments: dict):
    if name == "list_tables":
        return list_tables(conn)
    if name == "describe_table":
        return describe_table(conn, arguments.get("table", ""))
    if name == "run_query":
        return run_query(conn, arguments.get("sql", ""))
    raise ToolError(f"Unknown tool {name!r}.")
