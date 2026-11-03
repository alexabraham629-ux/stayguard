"""Canonical metric definitions: the source of truth (CLAUDE.md §5, docs/METRICS.md).

Every metric is computed here in pandas, independently of the SQL library. tests/test_sql.py
reconciles each SQL file against these functions, and the AI verifier (Phase 6) uses them as a
deterministic second opinion. All money is GBP (converted in v_bookings_gbp).

Usage:
    data = load_metric_data(con)
    expected_net_commission_gbp(data, Filters(countries=("UK",)))
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from stayguard.config import load_assumptions


@dataclass(frozen=True)
class Filters:
    """The app's global filters. An empty tuple means "all"."""

    countries: tuple[str, ...] = ()
    cities: tuple[str, ...] = ()
    intakes: tuple[str, ...] = ()
    channels: tuple[str, ...] = ()

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        mask = pd.Series(True, index=df.index)
        for column, values in (
            ("country", self.countries),
            ("city", self.cities),
            ("intake", self.intakes),
            ("channel", self.channels),
        ):
            if values:
                mask &= df[column].isin(values)
        return df.loc[mask]


ALL = Filters()


@dataclass(frozen=True)
class MetricData:
    """Base frames the metrics are computed from (loaded once per connection)."""

    bookings: pd.DataFrame  # v_bookings_gbp (clean, GBP) + p_cancel for open bookings
    leads: pd.DataFrame  # fact_lead + city, country, is_closed_intake
    agents: pd.DataFrame  # dim_agent
    assumptions: dict[str, Any] = field(repr=False)


def load_metric_data(con: duckdb.DuckDBPyConnection) -> MetricData:
    """Read the base frames through a (read-only) connection."""
    score_columns = {
        r[0]
        for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'scored_bookings'"
        ).fetchall()
    }
    # The deposit counterfactual exists once the Phase 4 model has scored (not for the baseline).
    extra = ", s.p_cancel_if_deposit" if "p_cancel_if_deposit" in score_columns else ""
    bookings = con.execute(
        f"""SELECT b.*, s.p_cancel{extra}
            FROM v_bookings_gbp AS b
            LEFT JOIN scored_bookings AS s ON s.booking_id = b.booking_id"""
    ).df()
    leads = con.execute(
        """SELECT l.*, c.city, c.country, i.is_closed AS is_closed_intake
           FROM fact_lead AS l
           JOIN dim_city AS c ON c.city_id = l.city_id
           JOIN dim_intake AS i ON i.intake = l.intake"""
    ).df()
    agents = con.execute("SELECT * FROM dim_agent").df()
    return MetricData(bookings, leads, agents, load_assumptions())


def _closed(df: pd.DataFrame) -> pd.DataFrame:
    return df.loc[df["is_closed_intake"]]


def _open(df: pd.DataFrame) -> pd.DataFrame:
    return df.loc[df["is_open"]]


# --- Revenue ------------------------------------------------------------------------------------


def gbv_gbp(d: MetricData, f: Filters = ALL) -> float:
    """Gross booking value: weekly rent x tenancy weeks, in GBP, over all clean bookings."""
    return float(f.apply(d.bookings)["gbv_gbp"].sum())


def _booked_by(b: pd.DataFrame, min_days_before_intake: int | None) -> pd.DataFrame:
    """Like-for-like: keep bookings made at least N days before move-in ("same point" in the
    cycle as today, when N is the days left to the open intake)."""
    if min_days_before_intake is None:
        return b
    return b.loc[b["days_booked_before_intake"] >= min_days_before_intake]


def booked_commission_gbp(
    d: MetricData, f: Filters = ALL, min_days_before_intake: int | None = None
) -> float:
    """GBV x commission rate (rate by operator type is an ASSUMPTION), all clean bookings."""
    return float(_booked_by(f.apply(d.bookings), min_days_before_intake)["commission_gbp"].sum())


def realised_commission_gbp(
    d: MetricData, f: Filters = ALL, min_days_before_intake: int | None = None
) -> float:
    """Commission on bookings that moved in."""
    b = _booked_by(f.apply(d.bookings), min_days_before_intake)
    return float(b.loc[b["is_moved_in"], "commission_gbp"].sum())


def expected_net_commission_gbp(d: MetricData, f: Filters = ALL) -> float:
    """North star. ENC = sum of commission x (1 - p_cancel) over open bookings."""
    b = _open(f.apply(d.bookings))
    return float((b["commission_gbp"] * (1 - b["p_cancel"])).sum())


def revenue_at_risk_gbp(d: MetricData, f: Filters = ALL) -> float:
    """Sum of commission x p_cancel over open bookings."""
    b = _open(f.apply(d.bookings))
    return float((b["commission_gbp"] * b["p_cancel"]).sum())


def live_commission_loss_share(d: MetricData, f: Filters, intake: str, days_left: int) -> float:
    """Share of the commission still live `days_left` days before move-in that is lost after it.

    Closed intake: what actually happened. Open intake: what the model expects
    (Revenue at Risk / open commission). Makes Revenue at Risk comparable across intakes.
    """
    b = f.apply(d.bookings)
    b = b.loc[b["intake"] == intake]
    if len(b) == 0:
        return float("nan")
    if not b["is_closed_intake"].iloc[0]:
        live = b.loc[b["is_open"]]
        return float(
            (live["commission_gbp"] * live["p_cancel"]).sum() / live["commission_gbp"].sum()
        )
    as_of = pd.Timestamp(b["intake_start_date"].iloc[0]) - pd.Timedelta(days=days_left)
    cancelled_before = b["is_cancelled"] & (b["cancelled_at"] < as_of)
    alive = (b["booked_at"] < as_of) & ~cancelled_before
    lost_after = alive & b["is_cancelled"]
    return float(b.loc[lost_after, "commission_gbp"].sum() / b.loc[alive, "commission_gbp"].sum())


def saveable_revenue_gbp(
    d: MetricData,
    f: Filters = ALL,
    top_n: int | None = None,
    save_rate: float | None = None,
) -> float:
    """Revenue at risk in the top-N of the action queue x assumed intervention save rate.

    Defaults: N = queue_top_share x open bookings; save rate from assumptions (both ASSUMPTIONS).
    """
    ops = d.assumptions["operations"]
    b = _open(f.apply(d.bookings))
    if top_n is None:
        top_n = int(round(ops["queue_top_share"] * len(b)))
    rate = ops["intervention_save_rate"] if save_rate is None else save_rate
    expected_loss = (b["commission_gbp"] * b["p_cancel"]).sort_values(ascending=False)
    return float(expected_loss.head(top_n).sum() * rate)


# --- Cancellation -------------------------------------------------------------------------------


def cancellation_rate(d: MetricData, f: Filters = ALL) -> float:
    """Cancelled / all clean bookings, closed intakes only (open outcomes are not final)."""
    b = _closed(f.apply(d.bookings))
    return float(b["is_cancelled"].mean())


def survival_rate(d: MetricData, f: Filters = ALL) -> float:
    """1 - cancellation rate: share of bookings that reached move-in."""
    return 1.0 - cancellation_rate(d, f)


def weekly_cancellation_rates(d: MetricData, city: str) -> pd.DataFrame:
    """Booking-week cohorts for one city with the 4-week pooled rolling cancellation rate."""
    b = _closed(d.bookings)
    weeks = b["booked_at"].dt.to_period("W-SUN").dt.start_time
    spine = pd.date_range(weeks.min(), weeks.max(), freq="7D")
    city_b = b.loc[b["city"] == city].assign(week_start=weeks)
    weekly = (
        city_b.groupby("week_start")["is_cancelled"]
        .agg(bookings="size", cancellations="sum")
        .reindex(spine, fill_value=0)
        .rename_axis("week_start")
        .reset_index()
    )
    rolling = weekly[["bookings", "cancellations"]].rolling(4, min_periods=1).sum()
    weekly["rolling_4wk_pooled_rate"] = rolling["cancellations"] / rolling["bookings"].replace(
        0, np.nan
    )
    return weekly


# --- Funnel & operations ------------------------------------------------------------------------


def lead_to_booking_conversion(d: MetricData, f: Filters = ALL) -> float:
    """Booked leads / leads, closed intakes only."""
    leads = _closed(f.apply(d.leads))
    return float((leads["status"] == "booked").mean())


def median_first_response_minutes(d: MetricData, f: Filters = ALL) -> float:
    """Median minutes to first response; missing values excluded (see missing_first_response)."""
    return float(f.apply(d.leads)["first_response_minutes"].dropna().median())


def missing_first_response_count(d: MetricData, f: Filters = ALL) -> int:
    """Contacted leads with no recorded first-response time (a data-quality gap, counted apart)."""
    leads = f.apply(d.leads)
    return int((leads["contacted_at"].notna() & leads["first_response_minutes"].isna()).sum())


def agent_load(d: MetricData) -> pd.Series:
    """Days of backlog per agent: open bookings / max daily capacity (ADR-007)."""
    open_per_agent = _open(d.bookings).groupby("agent_id").size()
    agents = d.agents.set_index("agent_id")
    return (
        open_per_agent.reindex(agents.index, fill_value=0) / agents["max_daily_capacity"]
    ).rename("load_days")


# --- Registry -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    label: str
    unit: str  # "gbp", "rate", "minutes", "count"
    function: Callable[..., float]
    sql_file: str
    owner: str


METRICS: dict[str, MetricDefinition] = {
    m.name: m
    for m in (
        MetricDefinition(
            "gbv", "Gross booking value", "gbp", gbv_gbp, "schema/02_views", "Finance"
        ),
        MetricDefinition(
            "booked_commission",
            "Booked commission",
            "gbp",
            booked_commission_gbp,
            "02_weekly_booking_velocity",
            "Finance",
        ),
        MetricDefinition(
            "realised_commission",
            "Realised commission",
            "gbp",
            realised_commission_gbp,
            "12_channel_unit_economics",
            "Finance",
        ),
        MetricDefinition(
            "expected_net_commission",
            "Expected net commission (ENC)",
            "gbp",
            expected_net_commission_gbp,
            "07_revenue_at_risk_by_city",
            "Finance",
        ),
        MetricDefinition(
            "revenue_at_risk",
            "Revenue at risk",
            "gbp",
            revenue_at_risk_gbp,
            "07_revenue_at_risk_by_city",
            "Finance",
        ),
        MetricDefinition(
            "saveable_revenue",
            "Saveable revenue",
            "gbp",
            saveable_revenue_gbp,
            "13_action_queue",
            "Ops",
        ),
        MetricDefinition(
            "cancellation_rate",
            "Cancellation rate",
            "rate",
            cancellation_rate,
            "03_cohort_cancellation_curve",
            "Revenue",
        ),
        MetricDefinition(
            "survival_rate",
            "Booking survival rate",
            "rate",
            survival_rate,
            "03_cohort_cancellation_curve",
            "Revenue",
        ),
        MetricDefinition(
            "lead_to_booking_conversion",
            "Lead-to-booking conversion",
            "rate",
            lead_to_booking_conversion,
            "01_funnel_by_city_intake",
            "City managers",
        ),
        MetricDefinition(
            "median_first_response",
            "Median first response",
            "minutes",
            median_first_response_minutes,
            "06_agent_leaderboard",
            "Ops",
        ),
        MetricDefinition(
            "missing_first_response",
            "Leads missing a first-response time",
            "count",
            missing_first_response_count,
            "14_data_quality_report",
            "Analytics",
        ),
    )
}
