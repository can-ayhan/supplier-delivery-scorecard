# Supplier Delivery Scorecard

Supplier performance report built from three SAP-style exports: purchase orders, goods receipts and quality inspection lots.

The goal is one place to answer "which suppliers deliver on time, in full, and without defects?" instead of stitching the three exports together by hand every month.

## Plan

1. Generate realistic exports to work with (no real company data in this repo)
2. Load them into PostgreSQL and clean up the SAP formatting
3. Validate: duplicates, ordered vs received mismatches
4. Model a star schema for delivery and quality KPIs
5. Power BI scorecard on top, plus an Excel workbook for ad hoc questions

## Status

Work in progress.
