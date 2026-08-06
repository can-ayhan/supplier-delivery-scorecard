from __future__ import annotations

import csv

from scorecard.config import RAW_DIR
from scorecard.generate import GR_FILE, MANIFEST_FILE, PO_FILE, QA_FILE, generate, sap_date, sap_number


def test_committed_exports_are_reproducible(tmp_path):
    """data/raw must be exactly what the generator writes for the default seed."""
    generate(tmp_path)
    for name in (PO_FILE, GR_FILE, QA_FILE, MANIFEST_FILE):
        assert (tmp_path / name).read_bytes() == (RAW_DIR / name).read_bytes(), name


def test_number_format():
    assert sap_number(1250.5) == "1.250,500"
    assert sap_number(-40) == "40,000-"
    assert sap_number(0.4, 2) == "0,40"
    assert sap_date(None) == ""


def test_receipts_reference_exported_po_lines(tmp_path):
    generate(tmp_path, seed=7)
    with (tmp_path / PO_FILE).open(encoding="cp1252", newline="") as fh:
        po_lines = {(r["EBELN"], r["EBELP"]) for r in csv.DictReader(fh, delimiter=";")}
    with (tmp_path / GR_FILE).open(encoding="ascii", newline="") as fh:
        receipts = list(csv.DictReader(fh, delimiter=";"))

    orphans = [r for r in receipts if (r["EBELN"], r["EBELP"]) not in po_lines]

    assert len(receipts) > 1000
    assert len(orphans) == 8  # only the planted ones
