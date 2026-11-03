"""Independent verification of every AI answer (CLAUDE.md §9.2): the "checks every number" story.

Three kinds of check, then one badge:
1. Canonical metric match: if the answer is a canonical metric, recompute it with metrics.py
   (pandas, independent of any SQL) and compare within the tolerance (0.5%).
2. Independent re-derivation: a SEPARATE model call with a different prompt, which never sees the
   first query, writes its own SQL; the two results are compared.
3. Sanity checks: currency mixing, raw duplicate rows, intakes named in the question but missing
   from the SQL, counts larger than the base tables, empty results.

Badge: any failed check -> Mismatch; otherwise a passed check 1 or 2 -> Verified; else Unverifiable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Literal

import duckdb
import pandas as pd
import sqlglot
from sqlglot import exp

from stayguard.ai.client import LLMClient
from stayguard.ai.nl2sql import QUERY_SCHEMA, Answer, generate_and_run
from stayguard.config import load_assumptions
from stayguard.metrics import METRICS, Filters, MetricData

CheckStatus = Literal["pass", "fail", "warn", "skipped"]
VerificationStatus = Literal["verified", "mismatch", "unverifiable"]
BADGES = {"verified": "✅ Verified", "mismatch": "⚠️ Mismatch", "unverifiable": "◻️ Unverifiable"}
DIMENSION_FILTER = {
    "country": "countries",
    "city": "cities",
    "intake": "intakes",
    "channel": "channels",
}
INTAKE_PATTERN = re.compile(r"\b(?:Sep|Jan)-20\d\d\b")
ACADEMIC_YEAR_PATTERN = re.compile(r"\b20\d\d-\d\d\b")
# Whole-word count names only: a bare "count" substring would also match "country".
COUNT_COLUMN = re.compile(
    r"(^n$|^count|_count$|^count_|^bookings$|^leads$|_bookings$|_leads$|^rows$)"
)


@dataclass
class Check:
    name: str
    status: CheckStatus
    detail: str


@dataclass
class Verification:
    status: VerificationStatus
    checks: list[Check] = field(default_factory=list)
    alternative: Answer | None = None

    @property
    def badge(self) -> str:
        return BADGES[self.status]


def _tolerance() -> float:
    return float(load_assumptions()["ai"]["verification_tolerance"])


def _close(value: float, expected: float, tol: float) -> bool:
    """Within tolerance, except that two whole numbers (counts) must match exactly: a booking
    count that is off by the duplicate rows is wrong, however small the difference."""
    if float(value).is_integer() and float(expected).is_integer():
        return value == expected
    return abs(value - expected) <= tol * abs(expected) + 1e-9


def _matches(value: float, expected: float, unit: str, tol: float) -> bool:
    """Rates may come back as a fraction (0.289) or a percentage (28.9)."""
    forms = [expected, expected * 100] if unit == "rate" else [expected]
    return any(_close(value, f, tol) for f in forms)


def _answer_values(rows: pd.DataFrame, column: str) -> pd.Series | None:
    if column in rows.columns and pd.api.types.is_numeric_dtype(rows[column]):
        return rows[column].astype(float)
    numeric = rows.select_dtypes("number").columns
    return rows[numeric[0]].astype(float) if len(numeric) == 1 else None


# --- 1. Canonical metric --------------------------------------------------------------------------


def canonical_metric_check(answer: Answer, data: MetricData) -> Check:
    spec = answer.canonical_metric or {}
    name = spec.get("name", "none")
    if name not in METRICS:
        return Check("Canonical metric", "skipped", "Not one of the canonical metrics.")
    metric = METRICS[name]
    values = _answer_values(answer.rows, answer.answer_column)
    if values is None:
        return Check("Canonical metric", "skipped", "Could not tell which column holds the answer.")
    filters = spec.get("filters", {})
    base = Filters(**{k: tuple(filters.get(k, [])) for k in DIMENSION_FILTER.values()})
    tol = _tolerance()
    group_by = spec.get("group_by", "none")

    if group_by == "none":
        if len(values) != 1:
            return Check("Canonical metric", "skipped", "Expected one number, got several rows.")
        expected = metric.function(data, base)
        ok = _matches(values.iloc[0], expected, metric.unit, tol)
        return Check(
            "Canonical metric",
            "pass" if ok else "fail",
            f"{metric.label}: query {values.iloc[0]:,.4g} vs metrics.py {expected:,.4g}"
            + ("" if ok else " (outside 0.5% tolerance)"),
        )

    if group_by not in answer.rows.columns:
        return Check("Canonical metric", "skipped", f"Result has no '{group_by}' column to match.")
    mismatches = []
    for key, value in zip(answer.rows[group_by], values, strict=True):
        f = replace(base, **{DIMENSION_FILTER[group_by]: (str(key),)})
        expected = metric.function(data, f)
        if not _matches(value, expected, metric.unit, tol):
            mismatches.append(f"{key}: query {value:,.4g} vs metrics.py {expected:,.4g}")
    if mismatches:
        return Check(
            "Canonical metric", "fail", f"{metric.label} differs for " + "; ".join(mismatches[:3])
        )
    return Check(
        "Canonical metric",
        "pass",
        f"{metric.label} matches metrics.py for all {len(values)} {group_by}s.",
    )


# --- 2. Independent re-derivation -----------------------------------------------------------------


def _scale(a: float, b: float) -> float | None:
    """1, 100 or 0.01: the factor that makes b comparable with a (fraction vs percentage)."""
    for factor in (1.0, 100.0, 0.01):
        if _close(a, b * factor, _tolerance()):
            return factor
    return None


def compare_results(first: Answer, second: Answer) -> Check:
    a = _answer_values(first.rows, first.answer_column)
    b = _answer_values(second.rows, second.answer_column)
    name = "Independent re-derivation"
    if a is None or b is None or a.empty or b.empty:
        return Check(name, "skipped", "Could not identify the answer column in both results.")
    if len(a) == 1 and len(b) == 1:
        ok = _scale(a.iloc[0], b.iloc[0]) is not None
        detail = f"first query {a.iloc[0]:,.4g} vs independent query {b.iloc[0]:,.4g}"
        return Check(name, "pass" if ok else "fail", detail)

    # Several rows: align on a label column the two results share.
    keys = [c for c in first.rows.columns if not pd.api.types.is_numeric_dtype(first.rows[c])]
    for key in keys:
        left = set(first.rows[key].astype(str))
        for other in second.rows.columns:
            right = set(second.rows[other].astype(str))
            if left and len(left & right) / len(left) >= 0.8:
                merged = pd.DataFrame(
                    {"key": first.rows[key].astype(str), "a": a.to_numpy()}
                ).merge(
                    pd.DataFrame({"key": second.rows[other].astype(str), "b": b.to_numpy()}),
                    on="key",
                )
                if merged.empty:
                    continue
                factor = _scale(merged["a"].iloc[0], merged["b"].iloc[0])
                ok = factor is not None and all(
                    _close(x, y * factor, _tolerance())
                    for x, y in zip(merged["a"], merged["b"], strict=True)
                )
                detail = f"{len(merged)} matching rows on '{key}'" + (
                    " agree" if ok else " disagree"
                )
                return Check(name, "pass" if ok else "fail", detail)
    return Check(name, "skipped", "The two results could not be aligned row by row.")


# --- 3. Sanity checks -----------------------------------------------------------------------------


def currency_mixing_check(sql: str) -> Check:
    """Flag SUM/AVG of a *_local money column with no FX conversion inside the aggregate."""
    name = "Currency mixing"
    tree = sqlglot.parse_one(sql, read="duckdb")
    for agg in tree.find_all(exp.Sum, exp.Avg):
        columns = {c.name.lower() for c in agg.find_all(exp.Column)}
        local = sorted(c for c in columns if c.endswith("_local"))
        if local and "fx_to_gbp" not in columns:
            return Check(
                name,
                "fail",
                f"{agg.key.upper()} over {', '.join(local)} adds GBP, AUD and EUR together. "
                "Use the *_gbp columns or multiply by fx_to_gbp.",
            )
    return Check(name, "pass", "No local-currency amounts are summed without FX conversion.")


def duplicates_check(sql: str) -> Check:
    tables = {t.name.lower() for t in sqlglot.parse_one(sql, read="duckdb").find_all(exp.Table)}
    if "fact_booking" in tables:
        return Check(
            "Duplicate rows",
            "warn",
            "Reads raw fact_booking, which includes data-entry duplicates; v_bookings_gbp "
            "removes them.",
        )
    return Check("Duplicate rows", "pass", "Uses de-duplicated bookings.")


def date_range_check(question: str, sql: str) -> Check:
    mentioned = set(INTAKE_PATTERN.findall(question)) | set(ACADEMIC_YEAR_PATTERN.findall(question))
    missing = sorted(m for m in mentioned if m not in sql)
    if missing:
        return Check(
            "Date range",
            "fail",
            f"The question mentions {', '.join(missing)} but the query does not filter on it.",
        )
    if mentioned:
        return Check("Date range", "pass", f"Query filters on {', '.join(sorted(mentioned))}.")
    return Check("Date range", "skipped", "The question names no intake or year.")


def row_count_check(answer: Answer, con: duckdb.DuckDBPyConnection) -> Check:
    tables = {
        t.name.lower() for t in sqlglot.parse_one(answer.sql, read="duckdb").find_all(exp.Table)
    }
    sizes = []
    for table in tables:
        try:
            sizes.append(con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        except duckdb.Error:
            continue  # CTE names are not tables
    count_columns = [
        c
        for c in answer.rows.select_dtypes("number").columns
        if COUNT_COLUMN.search(str(c).lower())
    ]
    if not sizes or not count_columns:
        return Check("Row counts", "skipped", "No count columns to check.")
    limit = max(sizes)
    too_big = [c for c in count_columns if answer.rows[c].max() > limit]
    if too_big:
        return Check(
            "Row counts",
            "fail",
            f"{', '.join(too_big)} exceeds the {limit:,} rows in the largest table queried "
            "(a join may be multiplying rows).",
        )
    return Check(
        "Row counts", "pass", f"Counts are within the size of the base tables ({limit:,})."
    )


def sanity_checks(answer: Answer, con: duckdb.DuckDBPyConnection) -> list[Check]:
    checks = [
        currency_mixing_check(answer.sql),
        duplicates_check(answer.sql),
        date_range_check(answer.question, answer.sql),
        row_count_check(answer, con),
    ]
    if answer.rows is not None and answer.rows.empty:
        checks.append(Check("Empty result", "warn", "The query returned no rows."))
    return checks


# --- Orchestration --------------------------------------------------------------------------------


def overall_status(checks: list[Check]) -> VerificationStatus:
    if any(c.status == "fail" for c in checks):
        return "mismatch"
    if any(
        c.status == "pass"
        for c in checks
        if c.name in ("Canonical metric", "Independent re-derivation")
    ):
        return "verified"
    return "unverifiable"


def verify(
    answer: Answer,
    con: duckdb.DuckDBPyConnection,
    client: LLMClient | None,
    data: MetricData,
) -> Verification:
    """Run every check on a successful answer and return the badge and the evidence."""
    checks = [canonical_metric_check(answer, data)]
    alternative = None
    if client is not None:
        alternative = generate_and_run(answer.question, con, client, "alt_sql_v1", QUERY_SCHEMA)
        if alternative.ok:
            checks.append(compare_results(answer, alternative))
        else:
            checks.append(
                Check(
                    "Independent re-derivation",
                    "skipped",
                    f"Second query failed: {alternative.error}",
                )
            )
    checks.extend(sanity_checks(answer, con))
    return Verification(overall_status(checks), checks, alternative)


def checks_as_dicts(checks: list[Check]) -> list[dict[str, str]]:
    return [{"name": c.name, "status": c.status, "detail": c.detail} for c in checks]
