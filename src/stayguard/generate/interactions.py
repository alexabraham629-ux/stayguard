"""Agent touchpoints (calls, WhatsApp, email) on leads and on bookings."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from stayguard.generate import reference as ref
from stayguard.generate._util import days, days_between, sample_categorical

INTERACTION_COLUMNS = [
    "interaction_id",
    "lead_id",
    "booking_id",
    "agent_id",
    "ts",
    "type",
    "outcome",
]


def _touches(
    rng: np.random.Generator,
    owner: pd.DataFrame,
    start: pd.Series,
    end: pd.Series,
    counts: np.ndarray,
    positive_prob: np.ndarray,
) -> pd.DataFrame:
    """Spread `counts[i]` touches uniformly between start[i] and end[i]."""
    idx = np.repeat(np.arange(len(owner)), counts)
    span = np.maximum(days_between(end, start), 0.0)[idx]
    ts = start.to_numpy()[idx] + days(rng.random(len(idx)) * span).to_numpy()
    group = owner["source_country"].map(ref.COUNTRY_GROUP).fillna(ref.DEFAULT_COUNTRY_GROUP)
    type_probs = np.array([ref.TOUCH_TYPE_MIX_BY_GROUP[g] for g in group], dtype=float)
    touch_type = np.array(ref.TOUCH_TYPES)[
        sample_categorical(rng.random(len(idx)), type_probs.reshape(-1, len(ref.TOUCH_TYPES))[idx])
    ]
    positive = rng.random(len(idx)) < positive_prob[idx]
    outcome = np.where(
        touch_type == "call",
        np.where(positive, "connected", "no_answer"),
        np.where(positive, "replied", "no_reply"),
    )
    return pd.DataFrame(
        {
            "agent_id": owner["agent_id"].to_numpy()[idx],
            "ts": ts,
            "type": touch_type,
            "outcome": outcome,
            "_owner_row": idx,
        }
    )


def build_interactions(
    rng: np.random.Generator,
    assumptions: dict[str, Any],
    leads: pd.DataFrame,
    bookings: pd.DataFrame,
) -> pd.DataFrame:
    """Lead touches (first response + follow-ups) and post-booking touches until move-in."""
    snapshot = pd.Timestamp(assumptions["project"]["snapshot_date"])
    follow_up = assumptions["generator"]["ground_truth"]["e7_overloaded_agents"][
        "follow_up_rate_multiplier"
    ]

    contacted = leads.loc[leads["contacted_at"].notna()].reset_index(drop=True)
    rate = np.where(contacted["_overloaded"], follow_up, 1.0)
    lead_counts = 1 + rng.poisson(ref.LEAD_EXTRA_TOUCHES_MEAN * rate)
    lead_touches = _touches(
        rng,
        contacted,
        contacted["contacted_at"],
        contacted["_lead_end"],
        lead_counts,
        np.full(len(contacted), ref.POSITIVE_OUTCOME_PROB),
    )
    # The first touch of every contacted lead is the first response itself.
    first = np.r_[0, np.cumsum(lead_counts)[:-1]]
    lead_touches.loc[first, "ts"] = contacted["contacted_at"].to_numpy()
    lead_touches["lead_id"] = contacted["lead_id"].to_numpy()[lead_touches["_owner_row"]]

    end = (
        bookings["_true_cancelled_at"]
        .fillna(bookings["_intake_start"])
        .clip(upper=bookings["_intake_start"])
        .clip(upper=snapshot)
    )
    rate = np.where(bookings["_overloaded"], follow_up, 1.0)
    booking_counts = rng.poisson(ref.BOOKING_TOUCHES_MEAN * rate)
    positive = np.where(
        bookings["_will_cancel"],
        ref.POSITIVE_OUTCOME_PROB_WILL_CANCEL,
        ref.POSITIVE_OUTCOME_PROB,
    )
    booking_touches = _touches(rng, bookings, bookings["booked_at"], end, booking_counts, positive)
    booking_touches["booking_id"] = bookings["booking_id"].to_numpy()[booking_touches["_owner_row"]]

    interactions = pd.concat([lead_touches, booking_touches], ignore_index=True)
    interactions = interactions.sort_values("ts", kind="mergesort").reset_index(drop=True)
    interactions["interaction_id"] = np.arange(1, len(interactions) + 1, dtype=np.int64)
    interactions["lead_id"] = interactions["lead_id"].astype("Int64")
    interactions["booking_id"] = interactions["booking_id"].astype("Int64")
    return interactions[INTERACTION_COLUMNS]
