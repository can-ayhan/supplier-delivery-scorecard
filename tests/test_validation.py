"""Every problem the generator plants has to be found, and nothing else.

planted_issues.json lists the keys of the rows that were deliberately broken.
Comparing as sets catches both a check that misses rows and a check that
flags clean ones.
"""

from __future__ import annotations

import json

import pytest

from scorecard.config import RAW_DIR

PLANTED = json.loads((RAW_DIR / "planted_issues.json").read_text(encoding="utf-8"))["planted"]


def sap_id(value: str) -> str:
    return value.lstrip("0") or "0"


def po_keys(name: str) -> set:
    return {(sap_id(po), int(item)) for po, item in PLANTED[name]}


def doc_keys(name: str) -> set:
    return {(sap_id(doc), int(year), int(item)) for doc, year, item in PLANTED[name]}


def lot_keys(name: str) -> set:
    return {sap_id(lot) for lot in PLANTED[name]}


def rejected_receipts(conn, reason: str) -> set:
    rows = conn.execute(
        "select doc_number, doc_year, doc_item from staging.v_goods_receipts_checked where reject_reason = %s",
        [reason],
    )
    return set(rows.fetchall())


def flagged_lines(conn, check_id: str) -> set:
    rows = conn.execute("select po_number, po_item from dq.issues where check_id = %s", [check_id])
    return set(rows.fetchall())


def flagged_lots(conn, check_id: str) -> set:
    rows = conn.execute(
        "select substr(record_key, 5) from dq.issues where check_id = %s", [check_id]
    )
    return {row[0] for row in rows}


def test_duplicate_po_lines(built):
    assert flagged_lines(built, "PO_DUPLICATE_LINE") == po_keys("duplicate_po_lines")


@pytest.mark.parametrize(
    "reason, planted",
    [
        ("GR_DUPLICATE_LINE", "duplicate_receipt_lines"),
        ("GR_UNREADABLE_VALUE", "receipt_bad_date"),
        ("GR_NO_PURCHASE_ORDER", "receipts_without_po"),
        ("GR_MATERIAL_MISMATCH", "receipt_material_mismatch"),
        ("GR_UOM_MISMATCH", "receipt_uom_mismatch"),
        ("GR_BEFORE_PO_DATE", "receipt_before_po_date"),
    ],
)
def test_rejected_receipts(built, reason, planted):
    assert rejected_receipts(built, reason) == doc_keys(planted)


def test_ordered_vs_received_mismatches(built):
    assert flagged_lines(built, "LINE_OVER_DELIVERY") == po_keys("over_delivery")
    assert flagged_lines(built, "LINE_CLOSED_SHORT") == po_keys("closed_short")


def test_receipts_on_deleted_lines(built):
    assert flagged_lines(built, "GR_ON_DELETED_LINE") == po_keys("deleted_line_with_receipt")


def test_inspection_lots(built):
    assert flagged_lots(built, "QA_DUPLICATE_LOT") == lot_keys("duplicate_lots")
    assert flagged_lots(built, "QA_NO_RECEIPT") == lot_keys("lots_without_receipt")


def test_rejected_rows_do_not_reach_the_valid_views(built):
    dropped = built.execute(
        "select count(*) from dq.issues i join dq.checks c using (check_id) where c.severity = 'error'"
    ).fetchone()[0]
    raw = built.execute(
        """select (select count(*) from staging.purchase_orders)
                + (select count(*) from staging.goods_receipts)
                + (select count(*) from staging.inspection_lots)"""
    ).fetchone()[0]
    valid = built.execute(
        """select (select count(*) from staging.v_purchase_orders_valid)
                + (select count(*) from staging.v_goods_receipts_valid)
                + (select count(*) from staging.v_inspection_lots_valid)"""
    ).fetchone()[0]
    assert raw - valid == dropped
