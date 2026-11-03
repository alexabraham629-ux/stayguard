"""Executive KPIs and headline insights, computed from metrics.py (no Streamlit here).

Every KPI compares like with like: the open intake against the same intake month a year earlier
at the same point in its cycle, and the latest closed intake against the one before it.
SQL equivalent: sql/15_commission_by_intake.sql (reconciled in tests/test_sql.py).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Literal

import pandas as pd

from stayguard.calendar import (
    comparable_intake,
    days_to_open_intake,
    latest_closed_intake,
    open_intake,
)
from stayguard.metrics import (
    Filters,
    MetricData,
    booked_commission_gbp,
    cancellation_rate,
    expected_net_commission_gbp,
    lead_to_booking_conversion,
    live_commission_loss_share,
    realised_commission_gbp,
    revenue_at_risk_gbp,
)


@dataclass(frozen=True)
class Kpi:
    label: str
    value: float
    unit: Literal["gbp", "pct"]
    delta: float  # relative change ("pct_change") or percentage points ("pp")
    delta_kind: Literal["pct_change", "pp"]
    comparison: str  # what the delta compares against, in plain English (tooltip)
    comparison_short: str  # e.g. 'vs Jan-26' (shown on the card)
    better_when: Literal["higher", "lower"]
    explanation: str
    metric_function: str
    sql_file: str


def _with_intake(f: Filters, intake: str) -> Filters:
    return replace(f, intakes=(intake,))


def _short(intake: str) -> str:
    """'Jan-2026' -> 'Jan-26'."""
    month, year = intake.split("-")
    return f"{month}-{year[2:]}"


def _pct_change(now: float, then: float) -> float:
    return now / then - 1 if then else float("nan")


def executive_kpis(d: MetricData, f: Filters) -> list[Kpi]:
    """The five Home KPIs. The intake filter is ignored: each card is pinned to its intakes."""
    a = d.assumptions
    now, then = open_intake(a), comparable_intake(open_intake(a))
    closed, closed_prev = latest_closed_intake(a), comparable_intake(latest_closed_intake(a))
    days_left = days_to_open_intake(a)
    f_now, f_then = _with_intake(f, now), _with_intake(f, then)
    sql = "15_commission_by_intake"

    booked_now = booked_commission_gbp(d, f_now)
    booked_then = booked_commission_gbp(d, f_then, min_days_before_intake=days_left)
    enc_now = expected_net_commission_gbp(d, f_now)
    landed_then = realised_commission_gbp(d, f_then, min_days_before_intake=days_left)
    risk_share_now = live_commission_loss_share(d, f, now, days_left)
    loss_share_then = live_commission_loss_share(d, f, then, days_left)
    cancel_now = cancellation_rate(d, _with_intake(f, closed))
    cancel_then = cancellation_rate(d, _with_intake(f, closed_prev))
    conv_now = lead_to_booking_conversion(d, _with_intake(f, closed))
    conv_then = lead_to_booking_conversion(d, _with_intake(f, closed_prev))

    return [
        Kpi(
            "Booked commission",
            booked_now,
            "gbp",
            _pct_change(booked_now, booked_then),
            "pct_change",
            f"vs {then} at the same point",
            f"vs {_short(then)}",
            "higher",
            f"Commission on every {now} booking so far (including those already cancelled), vs "
            f"{then} bookings made at least {days_left} days before move-in.",
            "metrics.booked_commission_gbp",
            sql,
        ),
        Kpi(
            "Expected to land",
            enc_now,
            "gbp",
            _pct_change(enc_now, landed_then),
            "pct_change",
            f"vs what {then} landed from bookings made by this point",
            f"vs {_short(then)}",
            "higher",
            "North star: open-booking commission x (1 - predicted cancellation risk).",
            "metrics.expected_net_commission_gbp",
            sql,
        ),
        Kpi(
            "Revenue at risk",
            revenue_at_risk_gbp(d, f_now),
            "gbp",
            risk_share_now - loss_share_then,
            "pp",
            f"{risk_share_now:.1%} of live commission at risk; {then} lost "
            f"{loss_share_then:.1%} from this point",
            f"vs {_short(then)}",
            "lower",
            "Open-booking commission x predicted cancellation risk. The delta compares the share "
            f"at risk with the share {then} actually lost after the same point in its cycle.",
            "metrics.revenue_at_risk_gbp, metrics.live_commission_loss_share",
            sql,
        ),
        Kpi(
            "Cancellation rate",
            cancel_now,
            "pct",
            cancel_now - cancel_then,
            "pp",
            f"vs {closed_prev}",
            f"vs {_short(closed_prev)}",
            "lower",
            "Cancelled / all bookings, for the latest intake that has moved in.",
            "metrics.cancellation_rate",
            sql,
        ),
        Kpi(
            "Lead conversion",
            conv_now,
            "pct",
            conv_now - conv_then,
            "pp",
            f"vs {closed_prev}",
            f"vs {_short(closed_prev)}",
            "higher",
            "Leads that booked / all leads, for the latest intake that has moved in.",
            "metrics.lead_to_booking_conversion",
            sql,
        ),
    ]


def commission_by_intake(d: MetricData, f: Filters) -> pd.DataFrame:
    """Per intake: realised and lost commission (closed) or ENC and risk (open)."""
    rows = []
    for intake in d.assumptions["intakes"]:
        fi = _with_intake(f, intake)
        b = fi.apply(d.bookings)
        if len(b) == 0:
            continue
        is_closed = bool(b["is_closed_intake"].iloc[0])
        rows.append(
            {
                "intake": intake,
                "is_closed": is_closed,
                "landed_or_expected_gbp": realised_commission_gbp(d, fi)
                if is_closed
                else expected_net_commission_gbp(d, fi),
                "lost_or_at_risk_gbp": float(b.loc[b["is_cancelled"], "commission_gbp"].sum())
                if is_closed
                else revenue_at_risk_gbp(d, fi),
                "booked_commission_gbp": booked_commission_gbp(d, fi),
            }
        )
    return pd.DataFrame(rows)


@dataclass(frozen=True)
class Insight:
    headline: str
    detail: str
    sql_file: str


def headline_insights(run: Callable[[str], pd.DataFrame]) -> list[Insight]:
    """Three rule-based insights from the SQL library (all markets). The verified AI memo
    replaces these in Phase 6. `run(name)` returns a named query's result."""
    risk = run("07_revenue_at_risk_by_city").sort_values("revenue_at_risk_gbp", ascending=False)
    top = risk.iloc[0]
    visa = run("09_source_country_visa_risk")
    visa = visa.loc[
        (~visa["small_sample"]) & visa["visa_status_at_booking"].isin(["pending", "not_applied"])
    ].sort_values("cancellation_pct", ascending=False)
    worst = visa.iloc[0]
    agents = run("06_agent_leaderboard").sort_values("load_days", ascending=False)
    a1, a2, rest = agents.iloc[0], agents.iloc[1], agents.iloc[2:]
    return [
        Insight(
            f"{top['city']} carries {top['share_of_total_risk_pct']:.0f}% of revenue at risk",
            f"£{top['revenue_at_risk_gbp']:,.0f} of open commission across "
            f"{int(top['open_bookings'])} bookings.",
            "07_revenue_at_risk_by_city",
        ),
        Insight(
            f"{worst['source_country']} students with visa "
            f"{worst['visa_status_at_booking'].replace('_', ' ')} cancel "
            f"{worst['cancellation_pct']:.0f}% of the time",
            f"{worst['visa_refusal_pct']:.0f}% of those bookings end in a visa refusal "
            f"({int(worst['bookings'])} bookings, closed intakes).",
            "09_source_country_visa_risk",
        ),
        Insight(
            f"{a1['agent_name']} and {a2['agent_name']} are overloaded",
            f"{a1['load_days']:.2f} and {a2['load_days']:.2f} days of backlog vs a team median of "
            f"{rest['load_days'].median():.2f}; their students cancel at "
            f"{a1['cancellation_pct']:.0f}% and {a2['cancellation_pct']:.0f}%.",
            "06_agent_leaderboard",
        ),
    ]
