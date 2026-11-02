"""Load and run the named queries in /sql (one file per business question)."""

from __future__ import annotations

import duckdb
import pandas as pd

from stayguard.config import SQL_DIR


def load_sql(name: str) -> str:
    """Return the text of sql/<name>.sql, e.g. load_sql('14_data_quality_report')."""
    path = SQL_DIR / f"{name}.sql"
    if not path.exists():
        raise FileNotFoundError(f"No SQL file named {name!r} in {SQL_DIR}")
    return path.read_text(encoding="utf-8")


def run_query(con: duckdb.DuckDBPyConnection, name: str) -> pd.DataFrame:
    """Run a named query and return the result as a DataFrame."""
    return con.execute(load_sql(name)).df()
