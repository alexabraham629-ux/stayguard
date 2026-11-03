"""Build the database if it is missing: used by the app on first boot when deployed (ADR-011).

Locally, `make data` does the same thing step by step. Deterministic: the same seed gives the
same data, model and scores everywhere.
"""

from __future__ import annotations

from pathlib import Path

from stayguard.config import DB_PATH
from stayguard.db import build_database
from stayguard.generate.pipeline import generate
from stayguard.model.pipeline import run_model_pipeline


def ensure_database(db_path: Path = DB_PATH) -> bool:
    """Generate data, build the database and score open bookings if the file is missing.

    Returns True if a build happened. The build writes to a temporary file first and renames it,
    so a half-built database is never left behind.
    """
    if db_path.exists():
        return False
    partial = db_path.with_name(db_path.stem + ".building.duckdb")
    partial.unlink(missing_ok=True)
    data = generate()
    build_database(data.tables, partial, data.manifest)
    run_model_pipeline(partial)
    partial.replace(db_path)
    return True
