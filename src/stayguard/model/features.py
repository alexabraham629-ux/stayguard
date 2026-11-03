"""Model features (as of a point before move-in) and the leakage guard."""

from __future__ import annotations

from typing import Any

import duckdb
import pandas as pd

from stayguard.sql_runner import run_query

FEATURES_SQL = "model/booking_features_as_of"

CATEGORICAL: list[str] = [
    "source_country",
    "visa_status_at_booking",
    "level",
    "channel",
    "operator_type",
    "room_type",
    "country",
    "intake_month",
]
NUMERIC: list[str] = [
    "days_booked_before_intake",  # days_since_booking would be this minus a constant: omitted
    "deposit_paid",
    "has_guarantor",
    "has_no_visa_no_pay",
    "cooling_off_days",
    "tenancy_weeks",
    "weekly_rent_gbp",
    "rent_to_budget",
    "property_rating",
    "distance_km_to_university",
    "first_response_minutes",
    "agent_load_vs_team",
    "touches_before_as_of",
    "positive_touch_rate_before_as_of",
]
FEATURES: list[str] = CATEGORICAL + NUMERIC

# Columns that reveal the outcome, or events after the scoring point. Never features.
LEAKY_COLUMNS: frozenset[str] = frozenset(
    {
        "target",
        "status",
        "is_cancelled",
        "is_moved_in",
        "is_open",
        "cancelled_at",
        "cancel_reason",
        "reason",
        "days_after_booking",
        "refund_amount_local",
        "refund_gbp",
        "has_invalid_cancel_timestamp",
        # interactions without the as-of cut-off (ADR-016)
        "touches_all_time",
        "positive_touch_rate_all_time",
    }
)
# Identifiers and bookkeeping columns: not leaky, but not features either.
NON_FEATURE_COLUMNS: frozenset[str] = frozenset(
    {"booking_id", "intake", "agent_id", "is_closed_intake", "commission_gbp", "as_of_ts", "split"}
)


class LeakageError(ValueError):
    """Raised when a feature list contains a column that leaks the outcome."""


def assert_no_leakage(features: list[str]) -> None:
    """Fail loudly if any feature reveals the outcome or post-scoring events."""
    leaky = sorted(set(features) & LEAKY_COLUMNS)
    if leaky:
        raise LeakageError(f"Leaky columns in feature list: {leaky}")


def assign_split(intake: pd.Series, assumptions: dict[str, Any]) -> pd.Series:
    """Time-based split from assumptions.yaml: train / validation / score (never random)."""
    split = assumptions["model_split"]
    mapping = {i: "train" for i in split["train_intakes"]}
    mapping |= {i: "validation" for i in split["validation_intakes"]}
    mapping |= {i: "score" for i in split["score_intakes"]}
    return intake.map(mapping)


def build_feature_frame(
    con: duckdb.DuckDBPyConnection, assumptions: dict[str, Any]
) -> pd.DataFrame:
    """One row per booking alive at its as-of point, with features, label, and split."""
    frame = run_query(con, FEATURES_SQL)
    frame["split"] = assign_split(frame["intake"], assumptions)
    for col in CATEGORICAL:
        # Fixed category sets across splits, so encodings match between training and scoring.
        frame[col] = pd.Categorical(frame[col].astype(str))
    for col in NUMERIC:
        frame[col] = frame[col].astype(float)
    return frame
