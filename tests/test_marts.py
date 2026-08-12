"""Delivery KPI logic and consistency of the star schema."""

from __future__ import annotations

import datetime as dt

import pytest

from scorecard.generate import GR_COLUMNS, GR_FILE, PO_COLUMNS, PO_FILE, QA_COLUMNS, QA_FILE
from scorecard.load import load_exports
from scorecard.pipeline import build

DUE = "10.06.2026"

# item -> (ordered, due, delivery completed flag, deleted flag)
PO_LINES = {
    10: (100, DUE, "", ""),
    20: (100, DUE, "", ""),
    30: (100, DUE, "X", ""),
    40: (100, DUE, "", ""),
    50: (100, DUE, "", ""),
    70: (100, "30.09.2026", "", ""),
    80: (100, DUE, "", ""),
    90: (100, DUE, "", "L"),
    100: (10, "31.07.2026", "", ""),
}

# (item, posting date, movement type, quantity as exported)
RECEIPTS = [
    (10, "09.06.2026", "101", "100,000"),      # complete, a day early
    (20, "08.06.2026", "101", "60,000"),       # split, second part late
    (20, "15.06.2026", "101", "40,000"),
    (30, "10.06.2026", "101", "80,000"),       # on time but short, then closed
    (50, "10.06.2026", "101", "98,000"),       # within the 2 % tolerance
    (80, "20.06.2026", "101", "70,000"),       # late and short
    (100, "31.07.2026", "101", "10,000"),      # pins the as-of date to 31.07.2026
]

EXPECTED = {
    # item: (status, on_time, in_full, otif, days_late)
    10: ("On time in full", True, True, True, -1),
    20: ("Late", False, True, False, 5),
    30: ("Short", True, False, False, 0),
    40: ("Not delivered", False, False, False, None),
    50: ("On time in full", True, True, True, 0),
    70: ("Open", False, False, False, None),
    80: ("Late and short", False, False, False, 10),
    100: ("On time in full", True, True, True, 0),
}


def write_export(path, columns, rows):
    lines = [";".join(columns)] + [";".join(row[c] for c in columns) for row in rows]
    path.write_text("\r\n".join(lines) + "\r\n", encoding="ascii")


@pytest.fixture
def scenario(conn, tmp_path):
    """A handful of PO lines with known outcomes, built through the real pipeline."""
    po_rows = [
        dict(EBELN="4500000001", EBELP=f"{item:05d}", BEDAT="01.06.2026", LIFNR="0000100234",
             NAME1="Test Supplier", LAND1="DE", MATNR="000000000040001000", TXZ01="Test part",
             MATKL="FAST", WERKS="1000", MENGE=f"{qty},000", MEINS="ST", NETPR="2,50", PEINH="1",
             WAERS="EUR", EINDT=due, LOEKZ=deleted, ELIKZ=closed)
        for item, (qty, due, closed, deleted) in PO_LINES.items()
    ]
    gr_rows = [
        dict(MBLNR=f"{5000000000 + n:010d}", MJAHR="2026", ZEILE="0001", BUDAT=posted, BWART=bwart,
             EBELN="4500000001", EBELP=f"{item:05d}", MATNR="000000000040001000", WERKS="1000",
             LIFNR="0000100234", MENGE=qty, MEINS="ST")
        for n, (item, posted, bwart, qty) in enumerate(RECEIPTS, start=1)
    ]
    write_export(tmp_path / PO_FILE, PO_COLUMNS, po_rows)
    write_export(tmp_path / GR_FILE, GR_COLUMNS, gr_rows)
    write_export(tmp_path / QA_FILE, QA_COLUMNS, [])

    load_exports(conn, tmp_path)
    build(conn)
    yield conn
    load_exports(conn)   # put the real exports back for the other tests
    build(conn)


def test_delivery_outcomes(scenario):
    rows = scenario.execute(
        """select po_item, delivery_status, is_on_time, is_in_full, is_otif, days_late
           from mart.fact_po_line"""
    ).fetchall()
    actual = {item: tuple(rest) for item, *rest in rows}

    assert actual == EXPECTED


def test_as_of_date_and_due_flag(scenario):
    as_of = scenario.execute("select as_of_date from mart.kpi_params").fetchone()[0]
    not_due = scenario.execute("select po_item from mart.fact_po_line where not is_due").fetchall()

    assert as_of == dt.date(2026, 7, 31)
    assert not_due == [(70,)]


def test_scenario_scorecard(scenario):
    due, otif, on_time, in_full = scenario.execute(
        "select due_lines, otif_pct, on_time_pct, in_full_pct from mart.v_supplier_scorecard"
    ).fetchone()

    assert due == 7                      # item 70 is not due, item 90 is cancelled
    assert float(otif) == 3 / 7
    assert float(on_time) == 4 / 7
    assert float(in_full) == 4 / 7


# consistency checks on the full data set ----------------------------------


def scalar(conn, sql: str):
    return conn.execute(sql).fetchone()[0]


def test_one_row_per_valid_po_line(built):
    facts = scalar(built, "select count(*) from mart.fact_po_line")
    expected = scalar(
        built,
        """select count(*)
           from staging.v_purchase_orders_valid p
           where not p.is_deleted
              or exists (select 1 from staging.v_goods_receipts_valid g
                         where g.po_number = p.po_number and g.po_item = p.po_item)""",
    )
    assert facts == expected


def test_received_quantity_equals_receipt_facts(built):
    mismatches = scalar(
        built,
        """select count(*)
           from mart.fact_po_line f
           left join (
               select po_line_key, sum(quantity) as qty
               from mart.fact_goods_receipt
               where movement_type in ('101', '102')
               group by po_line_key
           ) g using (po_line_key)
           where f.received_qty <> coalesce(g.qty, 0)""",
    )
    assert mismatches == 0


def test_otif_is_on_time_and_in_full(built):
    assert scalar(built, "select count(*) from mart.fact_po_line where is_otif <> (is_on_time and is_in_full)") == 0


def test_inspection_quantities_balance(built):
    unbalanced = scalar(
        built,
        """select count(*) from mart.fact_inspection
           where is_decided and accepted_qty + rejected_qty <> lot_qty""",
    )
    assert unbalanced == 0


def test_scorecard_matches_line_level_recalculation(built):
    lines = built.execute(
        "select supplier_id, sum(due_lines), sum(otif_lines) from mart.v_delivery_lines group by 1"
    ).fetchall()
    scorecard = dict(built.execute("select supplier_id, otif_pct from mart.v_supplier_scorecard").fetchall())

    assert len(lines) == len(scorecard) == 22
    for supplier_id, due, otif in lines:
        assert float(scorecard[supplier_id]) == pytest.approx(otif / due, abs=5e-5)


def test_ranks_cover_every_supplier(built):
    ranks = [r[0] for r in built.execute("select supplier_rank from mart.v_supplier_scorecard order by 1")]
    assert len(ranks) == 22
    assert ranks[0] == 1
    assert ranks[-1] <= 22
