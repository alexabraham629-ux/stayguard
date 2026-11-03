"""SQL guardrails for AI-written queries, enforced in code (CLAUDE.md §9.1), not just in the prompt.

1. Parse with sqlglot (DuckDB dialect); exactly one statement.
2. Only SELECT / WITH ... SELECT / set operations; no DML, DDL or commands anywhere.
3. Only whitelisted tables and views (plus the query's own CTE names); no table functions,
   file paths or other databases.
4. No functions that read files or the environment.
5. LIMIT forced to at most 1000 rows.
6. Executed on a READ-ONLY connection with a timeout.
"""

from __future__ import annotations

import threading

import duckdb
import pandas as pd
import sqlglot
from sqlglot import exp

from stayguard.ai.context import ALLOWED_TABLES
from stayguard.config import load_assumptions

FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = tuple(
    getattr(exp, name)
    for name in (
        "Insert",
        "Update",
        "Delete",
        "Merge",
        "Create",
        "Drop",
        "Alter",
        "Command",
        "Pragma",
        "Copy",
        "Attach",
        "Detach",
        "Use",
        "Set",
        "Transaction",
        "Commit",
        "Rollback",
        "LoadData",
    )
    if hasattr(exp, name)
)
FORBIDDEN_FUNCTIONS: frozenset[str] = frozenset(
    {
        "read_csv",
        "read_csv_auto",
        "read_parquet",
        "read_json",
        "read_json_auto",
        "read_json_objects",
        "read_ndjson",
        "read_text",
        "read_blob",
        "parquet_scan",
        "csv_scan",
        "sniff_csv",
        "glob",
        "query",
        "query_table",
        "getenv",
        "duckdb_secrets",
        "duckdb_settings",
        "install",
        "load",
    }
)
SET_OPERATIONS = tuple(
    getattr(exp, n) for n in ("SetOperation", "Union", "Intersect", "Except") if hasattr(exp, n)
)


class GuardrailError(ValueError):
    """The SQL was rejected before execution. The message is safe to show to users."""


def _function_name(node: exp.Func) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    return node.sql_name().lower()


def check_sql(sql: str, max_rows: int | None = None) -> str:
    """Validate AI-written SQL and return a safe version (with LIMIT). Raises GuardrailError."""
    max_rows = max_rows or int(load_assumptions()["ai"]["query_row_limit"])
    if not sql or not sql.strip():
        raise GuardrailError("The query is empty.")
    try:
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except sqlglot.errors.ParseError as e:
        raise GuardrailError(f"The query could not be parsed: {str(e).splitlines()[0]}") from e
    if len(statements) != 1:
        raise GuardrailError("Exactly one statement is allowed.")
    stmt = statements[0]

    if not isinstance(stmt, (exp.Select, *SET_OPERATIONS)):
        raise GuardrailError(f"Only SELECT queries are allowed (got {stmt.key.upper()}).")
    for node in stmt.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise GuardrailError(f"{node.key.upper()} is not allowed in a read-only query.")
        if isinstance(node, exp.Func) and _function_name(node) in FORBIDDEN_FUNCTIONS:
            raise GuardrailError(f"Function {_function_name(node)}() is not allowed.")

    cte_names = {cte.alias_or_name.lower() for cte in stmt.find_all(exp.CTE)}
    for table in stmt.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise GuardrailError("Table functions and file paths are not allowed in FROM.")
        if table.args.get("catalog") or (table.db and table.db.lower() != "main"):
            raise GuardrailError("Only tables in the StayGuard database can be queried.")
        name = table.name.lower()
        if name not in ALLOWED_TABLES and name not in cte_names:
            raise GuardrailError(f"Table '{table.name}' is not available to the AI.")

    limit = stmt.args.get("limit")
    limit_value = None
    if limit is not None:
        literal = limit.args.get("expression") or limit.this
        if isinstance(literal, exp.Literal) and literal.is_int:
            limit_value = int(literal.this)
    if limit_value is None or limit_value > max_rows:
        if isinstance(stmt, exp.Select):
            stmt = stmt.limit(max_rows, copy=True)
        else:
            stmt = exp.select("*").from_(stmt.subquery("ai_result")).limit(max_rows)
    return stmt.sql(dialect="duckdb")


def run_readonly(
    con: duckdb.DuckDBPyConnection, sql: str, timeout_s: float | None = None
) -> pd.DataFrame:
    """Run already-checked SQL on a read-only connection; interrupt it after `timeout_s`."""
    timeout_s = timeout_s or float(load_assumptions()["ai"]["query_timeout_seconds"])
    mode = con.execute("SELECT current_setting('access_mode')").fetchone()[0]
    if str(mode).lower() != "read_only":
        raise GuardrailError("AI queries must run on a read-only connection.")
    cursor = con.cursor()
    timer = threading.Timer(timeout_s, cursor.interrupt)
    timer.start()
    try:
        return cursor.execute(sql).df()
    except duckdb.InterruptException as e:
        raise GuardrailError(
            f"The query took longer than {timeout_s:.0f} s and was stopped."
        ) from e
    finally:
        timer.cancel()
        cursor.close()
