"""Score the assistant against a fixed question set with known answers.

Each question in evals/questions.json comes with a reference query. A question
passes when the rows of the assistant's last query contain the reference
result: every reference column has to show up as a column with the same
values, ignoring row order, column names and extra columns. Comparing result
sets instead of SQL text means any correct way of writing the query passes.
A rate counts as the same answer whether it comes back as 0.7561 or as 75.6.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import psycopg

from scorecard.assistant import agent, tools
from scorecard.config import ROOT

QUESTIONS_FILE = ROOT / "evals" / "questions.json"


@dataclass
class Result:
    id: str
    question: str
    passed: bool
    turns: int
    queries: int
    note: str = ""
    skipped: bool = False     # not run because the API rate limit was reached


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _same_value(expected, actual) -> bool:
    if _is_number(expected) and _is_number(actual):
        if 0 < abs(expected) <= 1:
            # a rate: the same answer as a fraction or as a percentage rounded to one decimal
            return abs(actual - expected) <= 0.00051 or abs(actual - 100 * expected) <= 0.051
        return abs(actual - expected) <= max(0.051, 1e-4 * abs(expected))
    if _is_number(expected) or _is_number(actual) or expected is None or actual is None:
        return expected is None and actual is None
    return str(expected).strip().casefold() == str(actual).strip().casefold()


def _sort_key(value):
    if value is None:
        return (0, 0.0, "")
    if _is_number(value):
        return (1, float(value), "")
    return (2, 0.0, str(value).strip().casefold())


def _same_column(expected: list, actual: list) -> bool:
    """Same values regardless of row order."""
    return all(_same_value(e, a) for e, a in zip(sorted(expected, key=_sort_key), sorted(actual, key=_sort_key)))


def same_result(expected: dict, actual: dict | None) -> bool:
    """True when every expected column appears among the actual columns."""
    if actual is None or len(expected["rows"]) != len(actual["rows"]):
        return False
    available = [[row[i] for row in actual["rows"]] for i in range(len(actual["columns"]))]
    for index in range(len(expected["columns"])):
        wanted = [row[index] for row in expected["rows"]]
        match = next((column for column in available if _same_column(wanted, column)), None)
        if match is None:
            return False
        available.remove(match)
    return True


def load_questions(path: Path = QUESTIONS_FILE) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate(conn: psycopg.Connection, client=None, questions: list[dict] | None = None,
             only: set[str] | None = None) -> list[Result]:
    results = []
    for item in questions or load_questions():
        if only and item["id"] not in only:
            continue
        if results and results[-1].skipped:
            results.append(Result(item["id"], item["question"], False, 0, 0, results[-1].note, skipped=True))
            continue
        expected = tools.run_query(conn, item["sql"])
        try:
            answer = agent.ask(item["question"], conn, client=client)
        except Exception as exc:
            if not agent.rate_limited(exc):
                raise
            # the free tier has a daily token allowance; the remaining questions would fail the same way
            results.append(Result(item["id"], item["question"], False, 0, 0, agent.api_message(exc), skipped=True))
            continue
        passed = same_result(expected, answer.last_result)
        note = "" if passed else (answer.last_result or {}).get("sql", answer.text[:120])
        results.append(Result(item["id"], item["question"], passed, answer.turns, len(answer.queries), note))
    return results


def print_report(results: list[Result]) -> None:
    for r in results:
        if r.skipped:
            print(f"SKIP  {r.id}")
            continue
        print(f"{'PASS' if r.passed else 'FAIL'}  {r.id:<28} turns={r.turns} queries={r.queries}")
        if not r.passed:
            print(f"      {r.question}\n      last query: {r.note}")
    ran = [r for r in results if not r.skipped]
    print(f"\n{sum(r.passed for r in ran)}/{len(ran)} questions answered with the reference result")
    if len(ran) < len(results):
        print(f"{len(results) - len(ran)} questions not run, the API rate limit was reached: {results[-1].note}")
