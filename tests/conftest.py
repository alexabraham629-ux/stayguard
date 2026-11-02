"""Shared fixtures: one full-scale dataset and database per test session (built in a temp dir)."""

from collections.abc import Iterator

import duckdb
import pytest

from stayguard.db import build_database, connect
from stayguard.generate.pipeline import GeneratedData, generate


@pytest.fixture(scope="session")
def generated() -> GeneratedData:
    return generate()


@pytest.fixture(scope="session")
def con(
    generated: GeneratedData, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[duckdb.DuckDBPyConnection]:
    db_path = tmp_path_factory.mktemp("db") / "stayguard.duckdb"
    build_database(generated.tables, db_path, generated.manifest)
    connection = connect(db_path, read_only=True)
    yield connection
    connection.close()


def scalar(con: duckdb.DuckDBPyConnection, sql: str) -> float:
    """Run a query that returns one value."""
    return con.execute(sql).fetchone()[0]
