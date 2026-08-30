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
        for table, rows in build(conn).items():
            print(f"{rows:>7,} rows  mart.{table}")
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


def cmd_excel(args: argparse.Namespace) -> int:
    from scorecard.db import connect
    from scorecard.excel import build_workbook

    with connect() as conn:
        path = build_workbook(conn, args.out, pivots=not args.no_pivots)
    print(f"workbook written to {path}")
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    from scorecard.assistant.agent import ask
    from scorecard.db import connect_reader

    with connect_reader() as conn:
        answer = ask(args.question, conn)
    print(answer.text)
    if args.show_sql:
        for query in answer.queries:
            print(f"-- {query['row_count']} rows")
            print(query["sql"])
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    from scorecard.assistant.evaluate import evaluate, print_report
    from scorecard.db import connect_reader

    only = set(args.only.split(",")) if args.only else None
    with connect_reader() as conn:
        print_report(evaluate(conn, only=only))
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

    p = sub.add_parser("build", help="clean, validate and rebuild the star schema")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("validate", help="show what the data quality checks found")
    p.add_argument("--export", type=Path, help="also write every finding to this CSV")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("excel", help="build the pivot workbook from the marts")
    p.add_argument("--out", type=Path, default=Path("excel/supplier_scorecard.xlsx"))
    p.add_argument("--no-pivots", action="store_true", help="skip the Excel step (no Windows / Excel needed)")
    p.set_defaults(func=cmd_excel)

    p = sub.add_parser("ask", help="ask the text-to-SQL assistant a question (needs a free Groq API key)")
    p.add_argument("question")
    p.add_argument("--show-sql", action="store_true", help="print the queries the assistant ran")
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("eval", help="score the assistant against evals/questions.json")
    p.add_argument("--only", help="comma separated question ids, to rerun a few")
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("run", help="load + build + validate")
    p.add_argument("--raw", type=Path, default=RAW_DIR)
    p.add_argument("--export", type=Path)
    p.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    from scorecard.config import ConfigError

    parser = build_parser()
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):      # answers and client names go beyond the console code page
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        if getattr(exc, "status_code", None) != 429:
            raise
        from scorecard.assistant.agent import api_message

        print(f"error: rate limit reached. {api_message(exc)}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
