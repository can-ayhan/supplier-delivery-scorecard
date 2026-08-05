"""Command line entry point: ``python -m scorecard <command>``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAW_DIR = Path("data/raw")


def cmd_generate(args: argparse.Namespace) -> int:
    from scorecard.generate import generate

    counts = generate(args.out, seed=args.seed)
    for name, rows in counts.items():
        print(f"{rows:>7,} rows  {args.out / name}")
    return 0


def cmd_load(args: argparse.Namespace) -> int:
    from scorecard.db import connect
    from scorecard.load import load_exports

    with connect() as conn:
        for table, rows in load_exports(conn, args.raw).items():
            print(f"{rows:>7,} rows  {table}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    from scorecard.db import connect
    from scorecard.pipeline import build

    with connect() as conn:
        build(conn)
    print("staging rebuilt")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    from scorecard.db import connect
    from scorecard.validate import export_issues, print_summary, summary

    with connect() as conn:
        print_summary(summary(conn))
        if args.export:
            count = export_issues(conn, args.export)
            print(f"{count} findings written to {args.export}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Load, build and validate in one go."""
    for step in (cmd_load, cmd_build, cmd_validate):
        print(f"\n== {step.__name__.removeprefix('cmd_')} ==")
        step(args)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scorecard", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("generate", help="write the three SAP-style exports")
    p.add_argument("--out", type=Path, default=RAW_DIR)
    p.add_argument("--seed", type=int, default=4217)
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("load", help="land the exports in the staging schema")
    p.add_argument("--raw", type=Path, default=RAW_DIR)
    p.set_defaults(func=cmd_load)

    p = sub.add_parser("build", help="rebuild the typed staging tables")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("validate", help="show what the data quality checks found")
    p.add_argument("--export", type=Path, help="also write every finding to this CSV")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("run", help="load + build + validate")
    p.add_argument("--raw", type=Path, default=RAW_DIR)
    p.add_argument("--export", type=Path)
    p.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
