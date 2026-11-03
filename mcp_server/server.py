"""StayGuard MCP server: lets Claude Code / Claude Desktop query the database, read-only.

Run:  uv run python mcp_server/server.py      (stdio; registered in .mcp.json)
Tools: list_tables, describe_table, run_readonly_query, get_metric.
Uses the MCP Python SDK 2.x, where FastMCP is called MCPServer (ADR-028).
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from stayguard.ai.audit import AuditLog
from stayguard.mcp_tools import Database, ToolInputError
from stayguard.metrics import METRICS

INSTRUCTIONS = """StayGuard: booking-risk data for a student-housing marketplace.
ALL DATA IS SYNTHETIC.
- Prefer the view v_bookings_gbp for bookings: duplicates removed, money already in GBP.
- Never sum *_local money columns across countries (GBP, AUD and EUR would be mixed).
- Outcome rates use closed intakes (is_closed_intake); Jan-2027 is the open intake, scored in
  scored_bookings.p_cancel.
- For headline numbers, prefer get_metric: it returns the canonical, tested value.
- Start with list_tables / describe_table if unsure of the schema."""

READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)

server = MCPServer(name="stayguard", instructions=INSTRUCTIONS)
db = Database(audit=AuditLog())


def _call(fn: Any, *args: Any) -> Any:
    try:
        return fn(*args)
    except ToolInputError as e:
        raise ToolError(str(e)) from e


@server.tool(annotations=READ_ONLY)
def list_tables() -> list[dict[str, Any]]:
    """List the tables and views you can query, with row counts and a one-line description."""
    return _call(db.list_tables)


@server.tool(annotations=READ_ONLY)
def describe_table(name: str) -> dict[str, Any]:
    """Columns (name, type, notes) and three sample rows for one table or view."""
    return _call(db.describe_table, name)


@server.tool(annotations=READ_ONLY)
def run_readonly_query(sql: str, max_rows: int = 200) -> dict[str, Any]:
    """Run ONE read-only DuckDB SELECT. Guardrails: SELECT/WITH only, whitelisted tables, no file
    or environment functions, LIMIT <= max_rows (max 1000), 10 s timeout. Returns the rows plus
    warnings (e.g. local currencies summed, raw duplicate rows)."""
    return _call(db.run_readonly_query, sql, max_rows)


GET_METRIC_DESCRIPTION = (
    "Canonical metric value from stayguard.metrics (the source of truth). "
    f"name: one of {', '.join(METRICS)}. "
    'filters (optional): {"countries": [...], "cities": [...], '
    '"intakes": [...], "channels": [...]}.'
)


@server.tool(annotations=READ_ONLY, description=GET_METRIC_DESCRIPTION)
def get_metric(name: str, filters: dict[str, list[str]] | None = None) -> dict[str, Any]:
    return _call(db.get_metric, name, filters)


if __name__ == "__main__":
    server.run("stdio")
