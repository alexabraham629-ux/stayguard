# StayGuard: Booking Risk Copilot

> **Synthetic data, portfolio project.** Inspired by the business model of student-housing
> marketplaces such as Amber. No real company data, names or brand assets are used.

StayGuard estimates how much booked commission will actually land, ranks which open bookings
booking managers should call today, and lets stakeholders ask the data questions in plain English,
with every AI answer checked against canonical metrics.

*This README is a stub. The portfolio version (findings, screenshots, architecture) lands in Phase 8.*

## Quick start (Windows or macOS)

Prerequisites: [uv](https://docs.astral.sh/uv/) and GNU make.

```bash
make setup   # creates .venv with Python 3.12 and installs dependencies
make data    # generates the synthetic data (~5 s) and builds data/stayguard.duckdb
make test    # runs the test suite (no API key needed)
make app     # launches the Streamlit app
```

Copy `.env.example` to `.env` and add your own `ANTHROPIC_API_KEY` to enable live AI features.
Without a key the app runs in Demo mode.

## Query the data from Claude (MCP)

`mcp_server/server.py` is a read-only [MCP](https://modelcontextprotocol.io) server. With it, Claude Code
or Claude Desktop can explore and query the StayGuard database directly. It needs no Anthropic API key:
the Claude client you already use does the reasoning.

| Tool | What it does |
|---|---|
| `list_tables` | Tables and views you may query, with row counts and descriptions |
| `describe_table(name)` | Columns, types, notes and three sample rows |
| `run_readonly_query(sql, max_rows=200)` | One SELECT through the app's guardrails (SELECT only, whitelisted tables, no file or env access, LIMIT ≤ 1000, 10 s timeout). Warns about summed local currencies and raw duplicate rows |
| `get_metric(name, filters)` | The canonical value from `stayguard.metrics`, e.g. `revenue_at_risk` for `{"cities": ["London"]}` |

Every tool is marked read-only, the database is opened read-only, and every query is logged to
`data/ai_audit.duckdb`.

**Claude Code:** the server is registered in `.mcp.json`. Start Claude Code in this folder, approve the
`stayguard` server when asked, then ask, for example, *"Using stayguard, which cities carry the most
revenue at risk?"*. Check it's connected with `claude mcp list`.

**Claude Desktop:** add this to `claude_desktop_config.json`, using your own path:

```json
{
  "mcpServers": {
    "stayguard": {
      "command": "uv",
      "args": ["run", "--directory", "C:/path/to/stayguard", "python", "mcp_server/server.py"]
    }
  }
}
```

Run `make data` first. Close the app and the MCP server before re-running `make data`: DuckDB allows
many read-only readers *or* one writer at a time.
