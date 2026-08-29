"""Guardrails for model-written SQL.

The assistant only ever gets to run what passes ``check``:

* exactly one statement, and it has to be a query
* nothing that writes, locks or changes anything, anywhere in the tree
* only the allow-listed tables of the mart schema (plus the query's own CTEs)
* no server-side functions that reach outside the query
* a row limit, added or lowered if the model did not set a sensible one

This is the first line of defence, not the only one: the query also runs as a
database role that can only SELECT from the mart schema, in a read-only
transaction with a statement timeout (see sql/07_assistant_role.sql).
"""

from __future__ import annotations

import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

SCHEMA = "mart"
ALLOWED_TABLES = {
    "dim_date", "dim_supplier", "dim_material", "dim_plant",
    "fact_po_line", "fact_goods_receipt", "fact_inspection",
    "v_delivery_lines", "v_supplier_scorecard", "v_supplier_month",
    "kpi_params",
}
MAX_ROWS = 200

_WRITES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter,
    exp.TruncateTable, exp.Copy, exp.Grant, exp.Command, exp.Into, exp.Lock, exp.Set,
    exp.Transaction, exp.Commit, exp.Rollback,
)
_BLOCKED_FUNCTIONS = re.compile(r"^(pg_|lo_|dblink|set_config|current_setting|query_to_xml|txid_)", re.I)


class QueryRejected(ValueError):
    """The query is not allowed. The message is written for the model to act on."""


def check(sql: str, max_rows: int = MAX_ROWS) -> str:
    """Return the SQL that may be executed, or raise QueryRejected."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except SqlglotError as exc:
        raise QueryRejected(f"The SQL could not be parsed: {exc}") from exc

    if len(statements) != 1:
        raise QueryRejected("Send exactly one statement.")
    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.SetOperation)):
        raise QueryRejected("Only SELECT queries are allowed.")

    forbidden = tree.find(*_WRITES)
    if forbidden is not None:
        raise QueryRejected(f"{forbidden.key.upper()} is not allowed, this connection is read-only.")

    ctes = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        name, schema = table.name.lower(), table.db.lower()
        if not schema and name in ctes:
            continue
        if table.catalog or schema not in ("", SCHEMA) or name not in ALLOWED_TABLES:
            allowed = ", ".join(sorted(ALLOWED_TABLES))
            raise QueryRejected(f"Table {table.sql()} is not available. Use one of: {allowed}.")

    for function in tree.find_all(exp.Anonymous):
        if _BLOCKED_FUNCTIONS.match(function.name):
            raise QueryRejected(f"Function {function.name} is not allowed.")

    limit = tree.args.get("limit")
    limit_value = limit.expression if limit is not None else None
    within_cap = (
        isinstance(limit_value, exp.Literal)
        and limit_value.is_int
        and int(limit_value.name) <= max_rows
    )
    if not within_cap:
        tree = tree.limit(max_rows)

    return tree.sql(dialect="postgres")
