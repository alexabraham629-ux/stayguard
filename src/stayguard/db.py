"""DuckDB connection helpers and the database build step."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from stayguard.config import DB_PATH, SQL_DIR, load_assumptions

TABLES_SQL = "schema/01_tables.sql"
VIEWS_SQL = "schema/02_views.sql"
BASELINE_SCORES_SQL = "schema/03_baseline_scores.sql"

# Assumptions the SQL library reads from meta_assumption: name -> (path in assumptions.yaml, text)
SQL_ASSUMPTIONS: dict[str, tuple[tuple[str, str], str]] = {
    "late_first_response_minutes": (
        ("operations", "late_first_response_minutes"),
        "First response slower than this (minutes) breaches the response SLA",
    ),
    "intervention_save_rate": (
        ("operations", "intervention_save_rate"),
        "Share of at-risk commission saved when an agent works a booking (ASSUMPTION)",
    ),
    "queue_top_share": (
        ("operations", "queue_top_share"),
        "Share of the open-booking queue the team works (model business metric)",
    ),
}


def connect(db_path: Path = DB_PATH, read_only: bool = True) -> duckdb.DuckDBPyConnection:
    """Open the database. The app, AI layer and MCP server always use read-only connections."""
    if read_only and not db_path.exists():
        raise FileNotFoundError(f"{db_path} not found. Run `make data` first.")
    return duckdb.connect(str(db_path), read_only=read_only)


def _assumption_rows(assumptions: dict[str, Any]) -> list[tuple[str, float, str]]:
    return [
        (name, float(assumptions[section][key]), text)
        for name, ((section, key), text) in SQL_ASSUMPTIONS.items()
    ]


def build_database(
    tables: dict[str, pd.DataFrame],
    db_path: Path = DB_PATH,
    manifest: dict[str, Any] | None = None,
    sql_dir: Path = SQL_DIR,
) -> None:
    """(Re)create the database: schema, metadata, data (FK order), views, baseline scores."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    for stale in (db_path, db_path.with_suffix(".duckdb.wal")):
        stale.unlink(missing_ok=True)

    con = duckdb.connect(str(db_path))
    try:
        con.execute((sql_dir / TABLES_SQL).read_text(encoding="utf-8"))
        if manifest is not None:
            con.execute(
                "INSERT INTO meta_build VALUES (?, ?, ?, ?)",
                [
                    manifest["snapshot_date"],
                    manifest["seed"],
                    manifest["scale"],
                    manifest["generator_version"],
                ],
            )
        con.executemany(
            "INSERT INTO meta_assumption VALUES (?, ?, ?)", _assumption_rows(load_assumptions())
        )
        for name, df in tables.items():  # dict order = FK-safe load order
            con.register("staging", df)
            con.execute(f"INSERT INTO {name} BY NAME SELECT * FROM staging")
            con.unregister("staging")
        con.execute((sql_dir / VIEWS_SQL).read_text(encoding="utf-8"))
        baseline = (sql_dir / BASELINE_SCORES_SQL).read_text(encoding="utf-8").rstrip().rstrip(";")
        con.execute(f"CREATE TABLE scored_bookings_baseline AS {baseline}")
        con.execute("CREATE TABLE scored_bookings AS SELECT * FROM scored_bookings_baseline")
        con.execute("CHECKPOINT")
    finally:
        con.close()
