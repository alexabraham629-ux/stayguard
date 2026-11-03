"""Does the model re-discover the planted cancellation effects (docs/DATA_GENERATION.md)?

Each check is a counterfactual: take the validation bookings, set one feature to a "reference" and
a "changed" value (everything else unchanged), and compare the model's mean predicted risk with the
direction the ground truth implies.

The model predicts risk AFTER the as-of point, for bookings that survived to it (ADR-005). For
lead time this flips the planted effect: early bookers cancel more overall, but their extra
cancellations (found cheaper, duplicate booking) are planted early in the booking window, so
those still alive 72 days before move-in are LOWER risk. The check expects that conditional
direction; the unconditional effect is tested on the raw data (tests/test_ground_truth_data.py).

Effects 4, 5, 6 and 8 concern conversion, demand and seasonality, not cancellation; the SQL
library and the ground-truth data tests cover them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

from stayguard.model.features import FEATURES


@dataclass(frozen=True)
class EffectCheck:
    effect: str
    description: str
    reference: dict[str, Any]
    changed: dict[str, Any]
    expected: Literal["higher", "lower"]  # expected risk of `changed` vs `reference`
    subset: str | None = None  # pandas query selecting the rows the check applies to


def with_overrides(X: pd.DataFrame, overrides: dict[str, Any]) -> pd.DataFrame:
    """Copy of X with the given columns set to one value (categories preserved)."""
    X = X.copy()
    for col, value in overrides.items():
        if isinstance(X[col].dtype, pd.CategoricalDtype):
            X[col] = pd.Categorical([value] * len(X), categories=X[col].cat.categories)
        else:
            X[col] = value
    return X


EFFECT_CHECKS: tuple[EffectCheck, ...] = (
    EffectCheck(
        "1. Visa status",
        "visa granted -> visa pending",
        {"visa_status_at_booking": "granted"},
        {"visa_status_at_booking": "pending"},
        "higher",
        "visa_status_at_booking != 'not_required'",
    ),
    EffectCheck(
        "1. Source country",
        "China -> Nigeria (both visa pending)",
        {"source_country": "China", "visa_status_at_booking": "pending"},
        {"source_country": "Nigeria", "visa_status_at_booking": "pending"},
        "higher",
        "visa_status_at_booking != 'not_required'",
    ),
    EffectCheck(
        "2. Deposit",
        "deposit paid -> no deposit",
        {"deposit_paid": 1.0},
        {"deposit_paid": 0.0},
        "higher",
    ),
    EffectCheck(
        "3. Booking lead time (given survival to 72 days out)",
        "booked 90 days before move-in -> 200 days before",
        {"days_booked_before_intake": 90.0},
        {"days_booked_before_intake": 200.0},
        "lower",
    ),
    EffectCheck(
        "7. Agent overload",
        "agent at team-average load -> 2.5x team average",
        {"agent_load_vs_team": 1.0},
        {"agent_load_vs_team": 2.5},
        "higher",
    ),
)


def recovery_table(model: Any, X: pd.DataFrame) -> pd.DataFrame:
    """Mean predicted p_cancel per counterfactual, and whether the expected direction holds."""
    rows = []
    for check in EFFECT_CHECKS:
        subset = X.query(check.subset) if check.subset else X
        p_ref = model.predict_proba(with_overrides(subset, check.reference)[FEATURES])[:, 1].mean()
        p_new = model.predict_proba(with_overrides(subset, check.changed)[FEATURES])[:, 1].mean()
        went_up = p_new > p_ref
        rows.append(
            {
                "effect": check.effect,
                "comparison": check.description,
                "rows": len(subset),
                "p_reference": float(p_ref),
                "p_changed": float(p_new),
                "relative_change": float(p_new / p_ref - 1),
                "expected": check.expected,
                "recovered": bool(went_up if check.expected == "higher" else not went_up),
            }
        )
    return pd.DataFrame(rows)
