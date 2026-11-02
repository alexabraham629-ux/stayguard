"""Data-quality report: runs sql/14_data_quality_report.sql and judges each check.

`python -m stayguard.quality.checks` prints the report for data/stayguard.duckdb.
"""

from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

from stayguard.db import connect
from stayguard.sql_runner import run_query

QUERY_NAME = "14_data_quality_report"


def run_quality_report(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """One row per check with a result: PASS / FAIL for integrity, DETECTED / MISSED for planted."""
    report = run_query(con, QUERY_NAME)
    failing = report["failing_rows"].to_numpy()
    category = report["category"].to_numpy()
    report["result"] = np.select(
        [
            (category == "integrity") & (failing == 0),
            category == "integrity",
            (category == "planted") & (failing > 0),
            category == "planted",
        ],
        ["PASS", "FAIL", "DETECTED", "MISSED"],
        default="INFO",
    )
    return report


def format_report(report: pd.DataFrame) -> str:
    """Plain-text table for the terminal."""
    lines = ["", "Data-quality report (sql/14_data_quality_report.sql)"]
    for row in report.itertuples(index=False):
        lines.append(
            f"  {row.check_id:<4} {row.result:<8} {row.failing_rows:>7,} / {row.total_rows:<8,}"
            f" {row.check_name}"
        )
    problems = report["result"].isin(["FAIL", "MISSED"]).sum()
    lines.append(f"  -> {'ALL CHECKS OK' if problems == 0 else f'{problems} PROBLEM(S)'}")
    return "\n".join(lines)


if __name__ == "__main__":
    with connect() as con:
        print(format_report(run_quality_report(con)))
