"""Logic behind the MCP server's tools (mcp_server/server.py), kept free of MCP so it is testable.

Every tool is read-only: the database is opened read-only, and SQL goes through the same
guardrails as the app's AI layer (ai/guardrails.py), plus the verifier's currency and duplicate
checks as warnings.
"""

from __future__ import annotations

import inspect
import json
import os
from functools import cached_property
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from stayguard.ai.audit import AuditLog, AuditRecord
from stayguard.ai.context import ALLOWED_TABLES, COLUMN_NOTES, TABLE_NOTES
from stayguard.ai.guardrails import GuardrailError, check_sql, run_readonly
from stayguard.ai.verifier import currency_mixing_check, duplicates_check
from stayguard.config import DB_PATH
from stayguard.metrics import METRICS, Filters, MetricData, load_metric_data

FILTER_KEYS = ("countries", "cities", "intakes", "channels")
FILTER_COLUMNS = {
    "countries": "country",
    "cities": "city",
    "intakes": "intake",
    "channels": "channel",
}
MAX_ROWS_LIMIT = 1000


class ToolInputError(ValueError):
    """A problem with the caller's input; the message is safe to show to the model."""


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return json.loads(df.to_json(orient="records", date_format="iso"))


class Database:
    """Lazily opened, read-only view of the StayGuard database."""

    def __init__(self, path: Path | None = None, audit: AuditLog | None = None) -> None:
        self.path = Path(path or os.getenv("STAYGUARD_DB_PATH") or DB_PATH)
        self.audit = audit

    @cached_property
    def con(self) -> duckdb.DuckDBPyConnection:
        if not self.path.exists():
            raise ToolInputError(f"Database not found at {self.path}. Run `make data` first.")
        return duckdb.connect(str(self.path), read_only=True)

    @cached_property
    def metric_data(self) -> MetricData:
        return load_metric_data(self.con.cursor())

    # --- tools -----------------------------------------------------------------------------------

    def list_tables(self) -> list[dict[str, Any]]:
        kinds = dict(
            self.con.execute(
                "SELECT table_name, table_type FROM information_schema.tables"
            ).fetchall()
        )
        return [
            {
                "name": name,
                "kind": "view" if "VIEW" in str(kinds[name]).upper() else "table",
                "rows": self.con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0],
                "description": TABLE_NOTES[name],
            }
            for name in ALLOWED_TABLES
            if name in kinds
        ]

    def describe_table(self, name: str) -> dict[str, Any]:
        if name not in ALLOWED_TABLES:
            raise ToolInputError(f"Unknown table '{name}'. Available: {', '.join(ALLOWED_TABLES)}.")
        columns = self.con.execute(
            """SELECT column_name, data_type FROM information_schema.columns
               WHERE table_name = ? ORDER BY ordinal_position""",
            [name],
        ).fetchall()
        sample = self.con.execute(f'SELECT * FROM "{name}" LIMIT 3').df()
        return {
            "name": name,
            "description": TABLE_NOTES[name],
            "columns": [
                {"name": c, "type": t, **({"note": COLUMN_NOTES[c]} if c in COLUMN_NOTES else {})}
                for c, t in columns
            ],
            "sample_rows": _records(sample),
        }

    def run_readonly_query(self, sql: str, max_rows: int = 200) -> dict[str, Any]:
        max_rows = max(1, min(int(max_rows), MAX_ROWS_LIMIT))
        try:
            safe_sql = check_sql(sql, max_rows=max_rows)
            rows = run_readonly(self.con, safe_sql)
        except GuardrailError as e:
            self._log(sql, "blocked", str(e))
            raise ToolInputError(f"Query rejected: {e}") from e
        except duckdb.Error as e:
            self._log(sql, "error", str(e).splitlines()[0])
            raise ToolInputError(f"Query failed: {str(e).splitlines()[0]}") from e
        warnings = [
            c.detail
            for c in (currency_mixing_check(safe_sql), duplicates_check(safe_sql))
            if c.status in ("fail", "warn")
        ]
        self._log(safe_sql, "ran", None)
        return {
            "sql_executed": safe_sql,
            "row_count": len(rows),
            "truncated": len(rows) >= max_rows,
            "columns": list(rows.columns),
            "rows": _records(rows),
            "warnings": warnings,
        }

    def get_metric(self, name: str, filters: dict[str, list[str]] | None = None) -> dict[str, Any]:
        if name not in METRICS:
            raise ToolInputError(f"Unknown metric '{name}'. Available: {', '.join(METRICS)}.")
        filters = filters or {}
        unknown = set(filters) - set(FILTER_KEYS)
        if unknown:
            raise ToolInputError(
                f"Unknown filter(s) {sorted(unknown)}. Use: {', '.join(FILTER_KEYS)}."
            )
        bookings = self.metric_data.bookings
        for key, values in filters.items():
            valid = set(bookings[FILTER_COLUMNS[key]].astype(str))
            bad = [v for v in values if v not in valid]
            if bad:
                raise ToolInputError(f"Unknown {key} {bad}. Valid: {sorted(valid)}.")
        metric = METRICS[name]
        f = Filters(**{k: tuple(filters.get(k, [])) for k in FILTER_KEYS})
        value = float(metric.function(self.metric_data, f))
        return {
            "metric": name,
            "label": metric.label,
            "value": value,
            "unit": metric.unit,
            "filters": {k: list(v) for k, v in filters.items()},
            "definition": inspect.getdoc(metric.function).splitlines()[0],
            "sql_reference": f"sql/{metric.sql_file}.sql",
            "owner": metric.owner,
            "source": "stayguard.metrics (canonical, reconciled with the SQL library in tests)",
        }

    def _log(self, sql: str, status: str, error: str | None) -> None:
        if self.audit is not None:
            self.audit.log(
                AuditRecord(
                    feature="mcp", generated_sql=sql, verification_status=status, error=error
                )
            )
