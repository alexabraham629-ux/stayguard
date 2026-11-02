"""DuckDB connection helpers and the database build step."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from stayguard.config import DB_PATH, SQL_DIR

SCHEMA_FILES = ("schema/01_tables.sql", "schema/02_views.sql")


def connect(db_path: Path = DB_PATH, read_only: bool = True) -> duckdb.DuckDBPyConnection:
    """Open the database. The app, AI layer and MCP server always use read-only connections."""
    if read_only and not db_path.exists():
        raise FileNotFoundError(f"{db_path} not found. Run `make data` first.")
    return duckdb.connect(str(db_path), read_only=read_only)


def build_database(
    tables: dict[str, pd.DataFrame],
    db_path: Path = DB_PATH,
    manifest: dict[str, Any] | None = None,
    sql_dir: Path = SQL_DIR,
) -> None:
    """(Re)create the database from scratch: schema, data (in FK order), then views."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    for stale in (db_path, db_path.with_suffix(".duckdb.wal")):
        stale.unlink(missing_ok=True)

    con = duckdb.connect(str(db_path))
    try:
        con.execute((sql_dir / SCHEMA_FILES[0]).read_text(encoding="utf-8"))
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
        for name, df in tables.items():  # dict order = FK-safe load order
            con.register("staging", df)
            con.execute(f"INSERT INTO {name} BY NAME SELECT * FROM staging")
            con.unregister("staging")
        con.execute((sql_dir / SCHEMA_FILES[1]).read_text(encoding="utf-8"))
        con.execute("CHECKPOINT")
    finally:
        con.close()
