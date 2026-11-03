"""Segment-rate baseline: the same rule as sql/schema/03_baseline_scores.sql, as an estimator.

Fitted only on the training rows, so it can be compared fairly with the ML models on validation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SEGMENT_COLUMNS = ["visa_status_at_booking", "deposit_paid", "lead_time_band"]
MIN_SEGMENT_SIZE = 50


def _segments(X: pd.DataFrame) -> pd.DataFrame:
    days = X["days_booked_before_intake"]
    band = np.select([days < 90, days < 180], ["under_90d", "90_179d"], "180d_plus")
    return pd.DataFrame(
        {
            "visa_status_at_booking": X["visa_status_at_booking"].astype(str).to_numpy(),
            "deposit_paid": X["deposit_paid"].to_numpy(),
            "lead_time_band": band,
        },
        index=X.index,
    )


class SegmentRateBaseline:
    """p_cancel = historical cancellation rate of the booking's segment (overall rate if thin)."""

    def fit(self, X: pd.DataFrame, y: pd.Series) -> SegmentRateBaseline:
        seg = _segments(X).assign(y=np.asarray(y))
        stats = seg.groupby(SEGMENT_COLUMNS)["y"].agg(["size", "mean"])
        self.overall_rate_ = float(np.mean(y))
        self.rates_ = stats.loc[stats["size"] >= MIN_SEGMENT_SIZE, "mean"]
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        keys = pd.MultiIndex.from_frame(_segments(X)[SEGMENT_COLUMNS])
        p = self.rates_.reindex(keys).fillna(self.overall_rate_).to_numpy()
        return np.column_stack([1 - p, p])
