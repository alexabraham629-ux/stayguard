"""Build the database if it is missing: used by the app on first boot when deployed (ADR-011).

Locally, `make data` does the same thing step by step. Deterministic: the same seed gives the
same data, model and scores everywhere.
"""

from __future__ import annotations

import time
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
    start = time.perf_counter()
    partial = db_path.with_name(db_path.stem + ".building.duckdb")
    partial.unlink(missing_ok=True)
    _progress("generating synthetic data", start)
    data = generate()
    _progress("building the database", start)
    build_database(data.tables, partial, data.manifest)
    _progress("training and scoring the model", start)
    run_model_pipeline(partial)
    partial.replace(db_path)
    _progress("done", start)
    return True


def _progress(step: str, start: float) -> None:
    """Print to stdout so first boot is visible in the hosting platform's logs."""
    print(f"[first boot +{time.perf_counter() - start:.0f}s] {step}", flush=True)
