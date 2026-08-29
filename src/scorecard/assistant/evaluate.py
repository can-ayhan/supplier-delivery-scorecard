"""Score the assistant against a fixed question set with known answers.

Each question in evals/questions.json comes with a reference query. A question
passes when the rows of the assistant's last query contain the reference
result: every reference column has to show up as a column with the same
values, ignoring row order, column names and extra columns. Comparing result
sets instead of SQL text means any correct way of writing the query passes.
"""

from __future__ import annotations

import json
from collections import Counter
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


def _normalise(value):
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 3)
    return str(value).strip()


def _column(rows: list[list], index: int) -> Counter:
    return Counter(_normalise(row[index]) for row in rows)


def same_result(expected: dict, actual: dict | None) -> bool:
    """True when every expected column appears among the actual columns."""
    if actual is None or len(expected["rows"]) != len(actual["rows"]):
        return False
    available = [_column(actual["rows"], i) for i in range(len(actual["columns"]))]
    for index in range(len(expected["columns"])):
        wanted = _column(expected["rows"], index)
        if wanted not in available:
            return False
        available.remove(wanted)
    return True


def load_questions(path: Path = QUESTIONS_FILE) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate(conn: psycopg.Connection, client=None, questions: list[dict] | None = None) -> list[Result]:
    results = []
    for item in questions or load_questions():
        expected = tools.run_query(conn, item["sql"])
        answer = agent.ask(item["question"], conn, client=client)
        passed = same_result(expected, answer.last_result)
        note = "" if passed else (answer.last_result or {}).get("sql", answer.text[:120])
        results.append(Result(item["id"], item["question"], passed, answer.turns, len(answer.queries), note))
    return results


def print_report(results: list[Result]) -> None:
    for r in results:
        print(f"{'PASS' if r.passed else 'FAIL'}  {r.id:<28} turns={r.turns} queries={r.queries}")
        if not r.passed:
            print(f"      {r.question}\n      last query: {r.note}")
    passed = sum(r.passed for r in results)
    print(f"\n{passed}/{len(results)} questions answered with the reference result")
