"""Cached, read-only data access for the app."""

from __future__ import annotations

import duckdb
import pandas as pd
import streamlit as st

from stayguard.config import DB_PATH, load_assumptions
from stayguard.metrics import MetricData, load_metric_data
from stayguard.sql_runner import load_sql, parse_header


@st.cache_resource(show_spinner=False)
def connection() -> duckdb.DuckDBPyConnection:
    """One read-only connection per server process; queries use per-call cursors (thread-safe)."""
    if not DB_PATH.exists():
        st.error("The database has not been built yet. Run `make data`, then reload this page.")
        st.stop()
    return duckdb.connect(str(DB_PATH), read_only=True)


@st.cache_data(show_spinner=False)
def query(name: str) -> pd.DataFrame:
    """Run a named query from /sql (result cached for the session's server)."""
    with connection().cursor() as cur:
        return cur.execute(load_sql(name)).df()


@st.cache_data(show_spinner=False)
def table(name: str) -> pd.DataFrame:
    """Read a whole table written by the pipeline (e.g. model_calibration)."""
    with connection().cursor() as cur:
        return cur.execute(f"SELECT * FROM {name}").df()  # name comes from code, never users


@st.cache_resource(show_spinner=False)
def metric_data() -> MetricData:
    with connection().cursor() as cur:
        return load_metric_data(cur)


@st.cache_data(show_spinner=False)
def header(name: str) -> dict[str, str]:
    return parse_header(name)


def assumptions() -> dict:
    return load_assumptions()
