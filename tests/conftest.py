"""Shared fixtures: one full-scale dataset, database and model run per test session (temp dir)."""

from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest

from stayguard.db import build_database, connect
from stayguard.generate.pipeline import GeneratedData, generate
from stayguard.model.pipeline import ModelRun, run_model_pipeline


@pytest.fixture(scope="session")
def generated() -> GeneratedData:
    return generate()


@pytest.fixture(scope="session")
def db_path(generated: GeneratedData, tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("db") / "stayguard.duckdb"
    build_database(generated.tables, path, generated.manifest)
    return path


@pytest.fixture(scope="session")
def model_run(db_path: Path) -> ModelRun:
    """Train and score once; must finish before any read-only connection is opened."""
    return run_model_pipeline(db_path)


@pytest.fixture(scope="session")
def con(db_path: Path, model_run: ModelRun) -> Iterator[duckdb.DuckDBPyConnection]:
    connection = connect(db_path, read_only=True)
    yield connection
    connection.close()


def scalar(con: duckdb.DuckDBPyConnection, sql: str) -> float:
    """Run a query that returns one value."""
    return con.execute(sql).fetchone()[0]
