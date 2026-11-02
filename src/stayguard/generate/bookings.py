"""Bookings and cancellations.

Cancellation is simulated as competing risks: each reason has its own intensity, built from the
planted effects (visa, deposit, lead time, budget fit, agent overload). The total intensity sets
the probability of cancelling; the reason is drawn in proportion to the intensities.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from stayguard.generate import reference as ref
from stayguard.generate._util import days, days_between, logit, sample_categorical, sigmoid

BOOKING_COLUMNS = [
    "booking_id",
    "lead_id",
    "student_id",
    "property_id",
    "agent_id",
    "booked_at",
    "intake",
    "tenancy_weeks",
    "weekly_rent_local",
    "currency",
    "gbv_local",
    "commission_rate",
    "commission_local",
    "deposit_paid",
    "visa_status_at_booking",
    "days_booked_before_intake",
    "status",
]
CANCELLATION_COLUMNS = [
    "booking_id",
    "cancelled_at",
    "reason",
    "refund_amount_local",
    "days_after_booking",
]


def _choose_properties(
    rng: np.random.Generator, booked: pd.DataFrame, properties: pd.DataFrame, fx: pd.Series
) -> np.ndarray:
    """Pick a property per booking, preferring rooms near the student's budget and well rated."""
    chosen = np.empty(len(booked), dtype=np.int64)
    for city_id, idx in booked.groupby("city_id").indices.items():
        props = properties.loc[properties["city_id"] == city_id]
        rent_gbp = props["weekly_rent_local"].to_numpy() * fx[city_id]
        budget = booked["budget_weekly_gbp"].to_numpy()[idx][:, None]
        over = np.clip(rent_gbp[None, :] - budget, 0, None) / (0.15 * budget)
        under = np.clip(budget - rent_gbp[None, :], 0, None) / (0.5 * budget)
        studio_pref = np.where(
            (booked["level"].to_numpy()[idx][:, None] == "PG")
            & (props["room_type"].to_numpy()[None, :] == "studio"),
            1.5,
            1.0,
        )
        weight = np.exp(-over - under) * props["rating"].to_numpy()[None, :] ** 2 * studio_pref
        pick = sample_categorical(rng.random(len(idx)), weight / weight.sum(axis=1, keepdims=True))
        chosen[idx] = props["property_id"].to_numpy()[pick]
    return chosen


def _tenancy_weeks(
    rng: np.random.Generator, intake_month: pd.Series, level: pd.Series
) -> np.ndarray:
    weeks = np.empty(len(level), dtype=int)
    u = rng.random(len(level))
    for (month, lvl), (options, probs) in ref.TENANCY_WEEKS.items():
        mask = ((intake_month == month) & (level == lvl)).to_numpy()
        cum = np.cumsum(probs)
        weeks[mask] = np.array(options)[np.searchsorted(cum, u[mask] * cum[-1], side="right")]
    return weeks


def _cancellation_intensity(
    b: pd.DataFrame, assumptions: dict[str, Any], rng: np.random.Generator
) -> np.ndarray:
    """(n, reasons) matrix of cancellation intensities, encoding planted effects 1, 2, 3 and 7."""
    gt = assumptions["generator"]["ground_truth"]
    e1, e3 = gt["e1_visa"], gt["e3_booking_lead_time"]
    bucket = np.digitize(b["days_booked_before_intake"].to_numpy(), e3["bucket_edges_days"])
    lam = np.zeros((len(b), len(ref.CANCEL_REASONS)))
    col = {reason: i for i, reason in enumerate(ref.CANCEL_REASONS)}
    base = ref.CANCEL_BASE_INTENSITY

    # Effect 1: visa refusal depends on source country and visa status at booking.
    lam[:, col["visa_refused"]] = (
        b["source_country"].map(e1["refusal_intensity_by_source_country"]).to_numpy()
        * b["visa_status_at_booking"].map(e1["status_multiplier"]).to_numpy()
    )
    lam[:, col["no_place"]] = base["no_place"] * b["level"].map(ref.NO_PLACE_LEVEL_MULT).to_numpy()
    lam[:, col["cooling_off"]] = base["cooling_off"] * (b["cooling_off_days"].to_numpy() > 0)
    # Effect 3: early bookers shop around (found_cheaper, duplicate_booking) and change plans.
    over_budget = np.clip(b["_rent_gbp"].to_numpy() / b["budget_weekly_gbp"].to_numpy() - 1, 0, 1)
    lam[:, col["found_cheaper"]] = (
        base["found_cheaper"]
        * np.array(e3["found_cheaper"])[bucket]
        * (1 + ref.OVER_BUDGET_SLOPE * over_budget)
    )
    lam[:, col["duplicate_booking"]] = (
        base["duplicate_booking"] * np.array(e3["duplicate_booking"])[bucket]
    )
    lam[:, col["changed_plans"]] = base["changed_plans"] * np.array(e3["changed_plans"])[bucket]
    lam[:, col["other"]] = base["other"]

    # Effect 2: no deposit -> weaker commitment (all non-visa reasons except no_place).
    no_deposit = np.where(b["deposit_paid"].to_numpy(), 1.0, gt["e2_no_deposit_multiplier"])
    for reason in ("cooling_off", "found_cheaper", "duplicate_booking", "changed_plans", "other"):
        lam[:, col[reason]] *= no_deposit
    # Effect 7: overloaded agents do not follow up, so their students drift away.
    overload = np.where(
        b["_overloaded"].to_numpy(), gt["e7_overloaded_agents"]["cancellation_multiplier"], 1.0
    )
    for reason in ("found_cheaper", "duplicate_booking", "changed_plans", "other"):
        lam[:, col[reason]] *= overload

    return lam * np.exp(rng.normal(0.0, ref.CANCEL_NOISE_SIGMA, size=len(b)))[:, None]


def _cancel_offset_days(
    rng: np.random.Generator, reason: np.ndarray, window: np.ndarray, cooling_days: np.ndarray
) -> np.ndarray:
    """Days from booking to cancellation, shaped by reason, always before move-in."""
    offset = np.zeros(len(reason))
    for name, (a, b) in ref.CANCEL_TIMING_BETA.items():
        mask = reason == name
        offset[mask] = window[mask] * rng.beta(a, b, size=int(mask.sum()))
    cooling = reason == "cooling_off"
    offset[cooling] = rng.uniform(0, np.minimum(cooling_days[cooling], window[cooling]))
    return np.clip(offset, 0.01, window * 0.999)


def _refund(rng: np.random.Generator, b: pd.DataFrame, deposit_weeks: float) -> np.ndarray:
    reason = b["reason"].to_numpy()
    share = np.array([ref.REFUND_SHARE.get(r, np.nan) for r in reason], dtype=float)
    visa = reason == "visa_refused"
    share[visa] = np.where(
        b["has_no_visa_no_pay"].to_numpy()[visa],
        ref.VISA_REFUND_SHARE_WITH_POLICY,
        ref.VISA_REFUND_SHARE_WITHOUT_POLICY,
    )
    other = np.isnan(share)
    options, probs = ref.OTHER_REFUND_OPTIONS
    share[other] = rng.choice(options, size=int(other.sum()), p=probs)
    deposit = b["weekly_rent_local"].to_numpy() * deposit_weeks * b["deposit_paid"].to_numpy()
    return np.round(deposit * share, 2)


def build_bookings(
    rng: np.random.Generator,
    assumptions: dict[str, Any],
    leads: pd.DataFrame,
    properties: pd.DataFrame,
    cities: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (bookings, cancellations); both keep internal `_` columns for later stages."""
    snapshot = pd.Timestamp(assumptions["project"]["snapshot_date"])
    commission_rates = assumptions["commission"]["rate_by_operator_type"]
    b = (
        leads.loc[leads["status"] == "booked"]
        .sort_values(["_booked_at", "lead_id"], kind="mergesort")
        .reset_index(drop=True)
    )
    n = len(b)
    fx = cities.set_index("city_id")["fx_to_gbp"]

    b["property_id"] = _choose_properties(rng, b, properties, fx)
    b = b.merge(
        properties[
            [
                "property_id",
                "operator_type",
                "room_type",
                "weekly_rent_local",
                "has_no_visa_no_pay",
                "cooling_off_days",
            ]
        ].rename(columns={"weekly_rent_local": "_property_rent"}),
        on="property_id",
        how="left",
    ).merge(cities[["city_id", "currency"]], on="city_id", how="left")

    b["booked_at"] = b["_booked_at"]
    b["tenancy_weeks"] = _tenancy_weeks(rng, b["_intake_month"], b["level"])
    b["weekly_rent_local"] = np.round(
        b["_property_rent"].to_numpy() * np.exp(rng.normal(0, ref.RENT_NOISE_SIGMA, size=n)), 2
    )
    b["_rent_gbp"] = b["weekly_rent_local"] * b["city_id"].map(fx)
    b["gbv_local"] = np.round(b["weekly_rent_local"] * b["tenancy_weeks"], 2)
    b["commission_rate"] = b["operator_type"].map(commission_rates).astype(float)
    b["commission_local"] = np.round(b["gbv_local"] * b["commission_rate"], 2)

    eff = ref.DEPOSIT_LOGIT_EFFECTS
    deposit_logit = (
        logit(ref.DEPOSIT_BASE_PROB)
        + eff["paid_search"] * (b["channel"] == "paid_search").to_numpy()
        + eff["has_guarantor"] * b["has_guarantor"].to_numpy()
        + eff["PG"] * (b["level"] == "PG").to_numpy()
    )
    b["deposit_paid"] = rng.random(n) < sigmoid(deposit_logit)

    window = days_between(b["_intake_start"], b["booked_at"])
    b["days_booked_before_intake"] = np.floor(window).astype(int)
    bucket = np.digitize(
        b["days_booked_before_intake"].to_numpy(),
        assumptions["generator"]["ground_truth"]["e3_booking_lead_time"]["bucket_edges_days"],
    )
    status_probs = np.array(ref.VISA_STATUS_BY_BUCKET)[bucket]
    visa_status = np.array(["not_applied", "pending", "granted"])[
        sample_categorical(rng.random(n), status_probs)
    ]
    b["visa_status_at_booking"] = np.where(b["visa_required"], visa_status, "not_required")

    lam = _cancellation_intensity(b, assumptions, rng)
    total = lam.sum(axis=1)
    will_cancel = rng.random(n) < 1 - np.exp(-total)
    reason = np.array(ref.CANCEL_REASONS)[
        sample_categorical(rng.random(n), lam / np.where(total > 0, total, 1)[:, None])
    ]
    offset = _cancel_offset_days(rng, reason, window, b["cooling_off_days"].to_numpy())
    cancelled_at = b["booked_at"] + days(offset)

    observed_cancel = will_cancel & (cancelled_at <= snapshot).to_numpy()
    b["status"] = np.select(
        [observed_cancel, b["_intake_closed"].to_numpy()], ["cancelled", "moved_in"], "open"
    )
    b["_will_cancel"] = will_cancel
    b["_true_cancelled_at"] = cancelled_at.where(will_cancel)
    b["cancelled_at"] = cancelled_at
    b["reason"] = reason
    b.insert(0, "booking_id", np.arange(1, n + 1, dtype=np.int64))

    c = b.loc[observed_cancel].copy()
    c["refund_amount_local"] = _refund(rng, c, assumptions["generator"]["deposit_weeks"])
    c["days_after_booking"] = np.floor(days_between(c["cancelled_at"], c["booked_at"])).astype(int)
    cancellations = c[[*CANCELLATION_COLUMNS, "booked_at", "_intake_start"]].reset_index(drop=True)
    return b.drop(columns=["cancelled_at", "reason"]), cancellations
