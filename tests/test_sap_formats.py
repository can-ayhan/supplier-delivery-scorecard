"""The staging.sap_* functions have to survive whatever the exports contain."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest


def call(conn, function: str, value):
    return conn.execute(f"select staging.{function}(%s::text)", [value]).fetchone()[0]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("31.07.2026", dt.date(2026, 7, 31)),
        (" 01.02.2025 ", dt.date(2025, 2, 1)),
        ("20260731", dt.date(2026, 7, 31)),      # internal format, shows up in some rows
        ("00.00.0000", None),                    # SAP's way of saying "no date"
        ("00000000", None),
        ("31.02.2026", None),
        ("2026-07-31", None),
        ("", None),
        (None, None),
    ],
)
def test_sap_date(built, raw, expected):
    assert call(built, "sap_date", raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1.250,500", Decimal("1250.5")),
        ("12.345.678,000", Decimal("12345678")),
        ("40,000-", Decimal("-40")),             # trailing minus on reversals
        ("-3,5", Decimal("-3.5")),
        ("0,000", Decimal("0")),
        ("1250,5", Decimal("1250.5")),
        (" 100 ", Decimal("100")),
        ("1,250.50", None),                      # US format is not expected, do not guess
        ("abc", None),
        ("", None),
        (None, None),
    ],
)
def test_sap_number(built, raw, expected):
    assert call(built, "sap_number", raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("0000104090", "104090"),
        ("104090", "104090"),                    # leading zeros lost in Excel
        (" 000000000040002027 ", "40002027"),
        ("0000", "0"),
        ("A-17", "A-17"),
        ("", None),
        (None, None),
    ],
)
def test_sap_id(built, raw, expected):
    assert call(built, "sap_id", raw) == expected
