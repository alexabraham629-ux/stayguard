"""Load and run the named queries in /sql (one file per business question)."""

from __future__ import annotations

import re

import duckdb
import pandas as pd

from stayguard.config import SQL_DIR

HEADER_KEYS = ("name", "business_question", "stakeholder", "techniques", "grain", "validated_by")
_HEADER_LINE = re.compile(r"^--\s*(\w+):\s*(.+)$")


def list_queries() -> list[str]:
    """Names of the numbered business queries, in order (e.g. '01_funnel_by_city_intake')."""
    return sorted(p.stem for p in SQL_DIR.glob("[0-9][0-9]_*.sql"))


def load_sql(name: str) -> str:
    """Return the text of sql/<name>.sql, e.g. load_sql('14_data_quality_report')."""
    path = SQL_DIR / f"{name}.sql"
    if not path.exists():
        raise FileNotFoundError(f"No SQL file named {name!r} in {SQL_DIR}")
    return path.read_text(encoding="utf-8")


def parse_header(name: str) -> dict[str, str]:
    """The `-- key: value` header block at the top of a query file."""
    header: dict[str, str] = {}
    for line in load_sql(name).splitlines():
        if not line.startswith("--"):
            break
        match = _HEADER_LINE.match(line)
        if match and match.group(1) in HEADER_KEYS:
            header[match.group(1)] = match.group(2).strip()
    return header


def run_query(con: duckdb.DuckDBPyConnection, name: str) -> pd.DataFrame:
    """Run a named query and return the result as a DataFrame."""
    return con.execute(load_sql(name)).df()
