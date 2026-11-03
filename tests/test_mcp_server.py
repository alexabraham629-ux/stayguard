"""MCP server: the tool logic, and the real server driven end-to-end over stdio by an MCP client."""

import json
import os
import sys

import anyio
import pytest
from mcp.client import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from stayguard.ai.audit import AuditLog
from stayguard.config import PROJECT_ROOT
from stayguard.mcp_tools import Database, ToolInputError
from stayguard.metrics import Filters, cancellation_rate, load_metric_data


@pytest.fixture(scope="module")
def tools(db_path, model_run, tmp_path_factory):
    return Database(db_path, audit=AuditLog(tmp_path_factory.mktemp("audit") / "a.duckdb"))


def test_list_tables_covers_the_whitelist(tools):
    tables = {t["name"]: t for t in tools.list_tables()}
    assert {"v_bookings_gbp", "fact_lead", "scored_bookings"} <= set(tables)
    assert tables["v_bookings_gbp"]["kind"] == "view" and tables["dim_city"]["rows"] == 12
    assert "ai_audit" not in tables and "model_evaluation" not in tables


def test_describe_table(tools):
    d = tools.describe_table("v_bookings_gbp")
    names = [c["name"] for c in d["columns"]]
    assert "commission_gbp" in names and len(d["sample_rows"]) == 3
    with pytest.raises(ToolInputError):
        tools.describe_table("ai_audit")


def test_query_runs_with_guardrails_and_warnings(tools):
    ok = tools.run_readonly_query("SELECT city, COUNT(*) AS n FROM v_bookings_gbp GROUP BY city", 5)
    assert ok["row_count"] == 5 and ok["truncated"] and "LIMIT 5" in ok["sql_executed"]
    warned = tools.run_readonly_query("SELECT SUM(gbv_local) AS total FROM fact_booking")
    assert len(warned["warnings"]) == 2  # mixed currencies + raw duplicate rows
    for bad in (
        "DROP TABLE dim_city",
        "SELECT * FROM read_csv('.env')",
        "SELECT nope FROM dim_city",
    ):
        with pytest.raises(ToolInputError):
            tools.run_readonly_query(bad)
    statuses = tools.audit.read()["verification_status"].tolist()
    assert statuses.count("blocked") == 2 and statuses.count("error") == 1


def test_get_metric_matches_metrics_py(tools, con):
    result = tools.get_metric("cancellation_rate", {"intakes": ["Sep-2026"]})
    expected = cancellation_rate(load_metric_data(con), Filters(intakes=("Sep-2026",)))
    assert result["value"] == pytest.approx(expected) and result["unit"] == "rate"
    for name, filters in (
        ("revenue", None),
        ("cancellation_rate", {"region": ["UK"]}),
        ("cancellation_rate", {"countries": ["France"]}),
    ):
        with pytest.raises(ToolInputError):
            tools.get_metric(name, filters)


def test_server_end_to_end_over_stdio(db_path, model_run):
    """Start the real server as a subprocess and call it like Claude Code would."""
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(PROJECT_ROOT / "mcp_server" / "server.py")],
        env={**os.environ, "STAYGUARD_DB_PATH": str(db_path)},
        cwd=str(PROJECT_ROOT),
    )

    async def session_calls():
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            tools = {t.name: t for t in (await session.list_tools()).tools}
            metric = await session.call_tool("get_metric", {"name": "expected_net_commission"})
            blocked = await session.call_tool(
                "run_readonly_query", {"sql": "DELETE FROM fact_booking"}
            )
            return tools, metric, blocked

    tools, metric, blocked = anyio.run(session_calls)
    assert set(tools) == {"list_tables", "describe_table", "run_readonly_query", "get_metric"}
    assert all(t.annotations.read_only_hint for t in tools.values())
    assert not any(t.annotations.destructive_hint for t in tools.values())
    assert tools["get_metric"].description.startswith("Canonical metric")
    payload = json.loads(metric.content[0].text)
    assert payload["metric"] == "expected_net_commission" and payload["value"] > 0
    assert blocked.is_error and "rejected" in blocked.content[0].text
