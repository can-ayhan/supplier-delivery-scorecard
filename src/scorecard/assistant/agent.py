"""Text-to-SQL assistant: plain-language question in, answer plus the SQL behind it out.

The model never sees the data directly. It has three tools (list the tables,
describe one, run a SELECT) and has to look at the schema before it writes a
query. Every query goes through the guard in ``guard.py`` and runs on a
read-only connection.

The model is an open model served through the Groq API; the free tier is
enough for the question set in evals/.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import psycopg

from scorecard.assistant import tools
from scorecard.config import ConfigError, get_settings

MAX_TURNS = 10

SYSTEM_PROMPT = """\
You answer questions about supplier delivery and incoming quality for a purchasing team. \
The data is a PostgreSQL star schema built from SAP purchase order, goods receipt and inspection lot exports.

How to work:
- Look before you write. Use list_tables and describe_table to get exact table, column and status names. \
Do not guess a column name.
- Answer from query results only. If the data cannot answer the question, say so instead of estimating.
- Prefer the views: v_supplier_scorecard for finished supplier KPIs, v_delivery_lines for anything \
that needs a different cut of the delivery data.
- Aggregate in SQL. Results are capped, so never pull detail rows to count them yourself.
- Let SQL do the arithmetic too. The last query you run has to return the figure you report \
(the rate itself, not the two totals to divide), so the answer can be checked against it.
- Report names, not internal codes or keys, whenever the table has both.

Definitions the business uses, apply them unless the question says otherwise:
- Delivery KPIs count due lines only: PO lines whose due date is on or before the as-of date in kpi_params.
- In full: net receipts reached the ordered quantity minus the in-full tolerance. On time: the receipt \
that completed the line was posted on or before the due date. OTIF: both.
- Rates are ratios of sums, for example sum(otif_lines) / sum(due_lines). Never average percentages \
across suppliers or months.
- Lead time is order date to the day the line was complete, in calendar days. Its average is taken over \
due lines that were delivered: avg(lead_time_days) does that, dividing by all due lines does not. Days late \
is delivery date minus due date; a line is late when days_late > 0.
- Defect rate is rejected quantity over inspected quantity, for lots with a usage decision (is_decided).

Give a short, direct answer with the figures that support it. State percentages with one decimal place. \
Mention the filter you applied when the question left room for interpretation."""


@dataclass
class Answer:
    text: str
    queries: list[dict] = field(default_factory=list)   # every query that ran, in order
    turns: int = 0
    stop_reason: str | None = None

    @property
    def last_result(self) -> dict | None:
        return self.queries[-1] if self.queries else None


def _client():
    import groq

    return groq.Groq(max_retries=5)      # reads GROQ_API_KEY; retries cover the free tier's rate limits


def _rejected_by_api(exc: Exception) -> str | None:
    """Groq answers 400 'tool_use_failed' when the model writes a tool call that does not fit the schema."""
    body = getattr(exc, "body", None)
    if getattr(exc, "status_code", None) == 400 and "tool_use_failed" in f"{body} {exc}":
        error = body.get("error", body) if isinstance(body, dict) else {}
        return str(error.get("message") or exc)
    return None


def rate_limited(exc: Exception) -> bool:
    return getattr(exc, "status_code", None) == 429


def api_message(exc: Exception) -> str:
    """The provider's own explanation of an error, without the surrounding payload."""
    body = getattr(exc, "body", None)
    error = body.get("error", body) if isinstance(body, dict) else {}
    return str(error.get("message") or exc)


def _run_tool(conn: psycopg.Connection, call, answer: Answer) -> str:
    """Execute one tool call and return what goes back to the model."""
    try:
        arguments = json.loads(call.function.arguments or "{}") or {}
        output = tools.call(conn, call.function.name, arguments)
    except json.JSONDecodeError as exc:
        return f"ERROR: the arguments are not valid JSON ({exc})"
    except tools.ToolError as exc:
        return f"ERROR: {exc}"
    if call.function.name == "run_query":
        answer.queries.append(output)
    return json.dumps(output, ensure_ascii=False)


def ask(question: str, conn: psycopg.Connection, client=None, model: str | None = None,
        max_turns: int = MAX_TURNS) -> Answer:
    """Run the tool loop until the model answers or the turn budget is used up."""
    model = model or get_settings().assistant_model
    if not model:
        raise ConfigError("Set SCORECARD_MODEL to the Groq model the assistant should use (see .env.example).")
    client = client or _client()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": question}]
    answer = Answer(text="")

    for turn in range(1, max_turns + 1):
        answer.turns = turn
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools.TOOL_DEFINITIONS,
                tool_choice="auto",
                temperature=0,
            )
        except Exception as exc:
            reason = _rejected_by_api(exc)
            if reason is None:
                raise
            messages.append({"role": "user",
                             "content": f"Your last tool call was not valid ({reason}). Call the tool again with valid arguments."})
            continue

        choice = response.choices[0]
        answer.stop_reason = choice.finish_reason
        calls = choice.message.tool_calls or []
        if not calls:
            answer.text = (choice.message.content or "").strip()
            if choice.finish_reason == "length":
                answer.text += "\n[answer cut off at the output limit]"
            return answer

        # replay the model's own calls, then one tool message per call
        messages.append({
            "role": "assistant",
            "content": choice.message.content or "",
            "tool_calls": [{"id": call.id, "type": "function",
                            "function": {"name": call.function.name, "arguments": call.function.arguments}}
                           for call in calls],
        })
        for call in calls:
            messages.append({"role": "tool", "tool_call_id": call.id, "content": _run_tool(conn, call, answer)})

    answer.text = f"No answer after {max_turns} turns."
    answer.stop_reason = "turn_limit"
    return answer
