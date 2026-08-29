from __future__ import annotations

import pytest

pytest.importorskip("sqlglot")

from scorecard.assistant.guard import MAX_ROWS, QueryRejected, check  # noqa: E402


@pytest.mark.parametrize(
    "sql",
    [
        "select count(*) from fact_po_line",
        "select s.region, count(*) from mart.fact_po_line f join mart.dim_supplier s using (supplier_key) group by 1",
        "with late as (select * from fact_po_line where days_late > 0) select count(*) from late",
        "select supplier_id from dim_supplier union select material_id from dim_material",
    ],
)
def test_allows_read_queries_on_the_marts(sql):
    assert check(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "delete from fact_po_line",
        "update fact_po_line set is_due = false",
        "insert into dim_plant (plant_id, plant_name) values ('9', 'x')",
        "drop table mart.fact_po_line",
        "create table x as select 1",
        "truncate mart.fact_po_line",
        "select 1; drop table mart.fact_po_line",                           # stacked statements
        "with d as (delete from fact_po_line returning *) select * from d",  # write hidden in a CTE
        "select * into backup from fact_po_line",
        "select * from fact_po_line for update",
        "select * from staging.purchase_orders",                             # not a mart table
        "select * from pg_catalog.pg_roles",
        "select * from information_schema.tables",
        "select pg_sleep(10)",
        "select pg_read_file('/etc/passwd')",
        "copy fact_po_line to '/tmp/out.csv'",
        "this is not sql",
        "",
    ],
)
def test_rejects_everything_else(sql):
    with pytest.raises(QueryRejected):
        check(sql)


def test_adds_a_row_limit():
    assert check("select * from v_delivery_lines").endswith(f"LIMIT {MAX_ROWS}")


def test_lowers_a_limit_above_the_cap_and_keeps_a_smaller_one():
    assert check("select * from v_delivery_lines limit 100000").endswith(f"LIMIT {MAX_ROWS}")
    assert check("select * from v_delivery_lines limit 5").endswith("LIMIT 5")


def test_a_cte_may_not_shadow_its_way_past_the_allow_list():
    # the CTE is called like an allowed name, but what it reads is still checked
    with pytest.raises(QueryRejected):
        check("with dim_supplier as (select * from staging.purchase_orders) select * from dim_supplier")
