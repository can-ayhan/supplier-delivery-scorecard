"""The assistant's tool loop, driven by a scripted stand-in for the model.

No API key is needed: the fake client replays canned responses, which is
enough to test that tool calls are executed, guarded and fed back correctly.
"""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import psycopg
import pytest

pytest.importorskip("sqlglot")

from scorecard.assistant import agent, tools  # noqa: E402
from scorecard.db import connect_reader  # noqa: E402


@pytest.fixture
def reader(built, monkeypatch):
    monkeypatch.setenv("SCORECARD_MODEL", "scripted-model")   # the fake client ignores it, ask() requires one
    conn = connect_reader()
    yield conn
    conn.close()


def call(name: str, call_id: str, **arguments):
    return SimpleNamespace(id=call_id, type="function",
                           function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))


def calls(*tool_calls):
    """A model turn that asks for tools."""
    message = SimpleNamespace(content=None, tool_calls=list(tool_calls))
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="tool_calls")])


def text(value: str, finish_reason: str = "stop"):
    """A model turn that answers."""
    message = SimpleNamespace(content=value, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)])


class FakeClient:
    """Returns the scripted responses in order and records every request."""

    def __init__(self, *turns):
        self.turns = list(turns)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **request):
        self.requests.append(copy.deepcopy(request))
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        return turn


def tool_messages(request: dict) -> list[dict]:
    """The tool results at the end of a request, in order."""
    results = []
    for message in reversed(request["messages"]):
        if message["role"] != "tool":
            break
        results.insert(0, message)
    return results


def test_runs_tools_and_returns_the_answer_with_its_sql(reader):
    client = FakeClient(
        calls(call("describe_table", "t1", table="dim_supplier")),
        calls(call("run_query", "t2", sql="select count(*) from dim_supplier")),
        text("There are 22 suppliers."),
    )

    answer = agent.ask("How many suppliers are there?", reader, client=client)

    assert answer.text == "There are 22 suppliers."
    assert answer.turns == 3
    assert answer.last_result["rows"] == [[22]]
    assert answer.last_result["sql"].endswith("LIMIT 200")

    # the query result went back to the model as the reply to the right call
    last_request = client.requests[-1]
    result = last_request["messages"][-1]
    assert result["role"] == "tool" and result["tool_call_id"] == "t2"
    assert json.loads(result["content"])["rows"] == [[22]]
    assert last_request["messages"][-2]["tool_calls"][0]["id"] == "t2"      # the model's own call is replayed first
    assert last_request["tools"] == tools.TOOL_DEFINITIONS
    assert last_request["messages"][0]["role"] == "system"


def test_rejected_query_is_reported_back_as_an_error(reader):
    client = FakeClient(
        calls(call("run_query", "t1", sql="delete from fact_po_line")),
        text("I can only read the data."),
    )

    answer = agent.ask("Delete the late lines", reader, client=client)

    result = client.requests[-1]["messages"][-1]
    assert result["content"].startswith("ERROR:")
    assert "Only SELECT" in result["content"]
    assert answer.queries == []


def test_sql_error_does_not_break_the_connection(reader):
    client = FakeClient(
        calls(call("run_query", "t1", sql="select no_such_column from dim_supplier")),
        calls(call("run_query", "t2", sql="select count(*) from dim_plant")),
        text("3 plants."),
    )

    answer = agent.ask("How many plants?", reader, client=client)

    first_result = client.requests[1]["messages"][-1]
    assert first_result["content"].startswith("ERROR:") and "no_such_column" in first_result["content"]
    assert answer.last_result["rows"] == [[3]]


def test_every_parallel_tool_call_gets_its_own_reply(reader):
    client = FakeClient(
        calls(call("describe_table", "a", table="dim_plant"), call("describe_table", "b", table="dim_date")),
        text("done"),
    )

    agent.ask("Describe two tables", reader, client=client)

    assert [m["tool_call_id"] for m in tool_messages(client.requests[-1])] == ["a", "b"]


def test_arguments_that_are_not_json_are_reported_back(reader):
    broken = call("run_query", "t1")
    broken.function.arguments = "{sql: select 1"
    client = FakeClient(calls(broken), text("sorry"))

    agent.ask("anything", reader, client=client)

    assert "not valid JSON" in client.requests[-1]["messages"][-1]["content"]


def test_stops_at_the_turn_limit(reader):
    endless = [calls(call("list_tables", f"t{i}")) for i in range(5)]
    answer = agent.ask("loop", reader, client=FakeClient(*endless), max_turns=3)

    assert answer.stop_reason == "turn_limit"
    assert answer.turns == 3


def test_tool_call_rejected_by_the_api_is_retried(reader):
    class ToolUseFailed(Exception):
        status_code = 400
        body = {"error": {"code": "tool_use_failed", "message": "tool call validation failed"}}

    class RateLimited(Exception):
        status_code = 429
        body = {"error": {"code": "rate_limit_exceeded"}}

    client = FakeClient(ToolUseFailed("400"), text("22 suppliers."))
    answer = agent.ask("How many suppliers?", reader, client=client)

    assert answer.text == "22 suppliers." and answer.turns == 2
    assert "not valid" in client.requests[-1]["messages"][-1]["content"]
    with pytest.raises(RateLimited):                     # anything else is the caller's problem
        agent.ask("How many suppliers?", reader, client=FakeClient(RateLimited("429")))


def test_model_comes_from_the_settings_and_has_no_default(reader, monkeypatch):
    client = FakeClient(text("ok"))
    agent.ask("anything", reader, client=client)
    assert client.requests[0]["model"] == "scripted-model"

    monkeypatch.setenv("SCORECARD_MODEL", "")
    with pytest.raises(agent.ConfigError, match="SCORECARD_MODEL"):
        agent.ask("anything", reader, client=FakeClient())


def test_reader_role_cannot_write_or_leave_the_marts(reader):
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        reader.execute("delete from mart.dim_plant")
    reader.rollback()
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        reader.execute("select count(*) from staging.purchase_orders")
    reader.rollback()


def test_describe_table_lists_status_values(reader):
    described = tools.describe_table(reader, "fact_po_line")
    status = next(c for c in described["columns"] if c["column"] == "delivery_status")

    assert "On time in full" in status["values"]
    with pytest.raises(tools.ToolError):
        tools.describe_table(reader, "pg_roles")
