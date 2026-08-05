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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
