"""Students and leads: volumes, seasonality, channels, response times and the sales funnel.

Every lead's full lifecycle is simulated, then censored at the snapshot date: events after
"today" are removed, so open-intake leads show the stage they had reached by 2026-10-31.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from stayguard.generate import reference as ref
from stayguard.generate._util import days, sample_categorical, sigmoid

MONTH_NUMBER: dict[str, int] = {
    name: i
    for i, name in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        start=1,
    )
}

STUDENT_COLUMNS = [
    "source_country",
    "level",
    "university_id",
    "budget_weekly_gbp",
    "has_guarantor",
    "visa_required",  # internal: drives visa status at booking, not published in dim_student
]


def _pg_keep_probability(ground_truth: dict[str, Any], year: str, city: str, market: str) -> float:
    """Effect 6: share of PG leads kept for this academic year and market segment."""
    table = ground_truth["e6_pg_demand_multiplier"][year]
    if market != "UK":
        return float(table["au_ie"])
    return float(table["london"] if city == "London" else table["uk_non_london"])


def _created_at(
    rng: np.random.Generator, n: int, season: dict[str, float], intake_start: pd.Timestamp
) -> pd.Series:
    """Effect 8: lead creation timestamps following the intake's monthly seasonality."""
    names = list(season)
    p = np.array(list(season.values()), dtype=float)
    month = np.array([MONTH_NUMBER[m] for m in names])[
        rng.choice(len(names), size=n, p=p / p.sum())
    ]
    # Months on or after the intake month belong to the previous calendar year.
    year = np.where(month >= intake_start.month, intake_start.year - 1, intake_start.year)
    month_start = pd.to_datetime(pd.DataFrame({"year": year, "month": month, "day": 1}))
    day = np.floor(rng.random(n) * month_start.dt.days_in_month.to_numpy())
    seconds = rng.integers(7 * 3600, 24 * 3600, size=n)
    return month_start + days(day) + pd.to_timedelta(seconds, unit="s")


def _lead_block(
    rng: np.random.Generator,
    assumptions: dict[str, Any],
    intake: Any,
    city: Any,
    universities: pd.DataFrame,
    agents: pd.DataFrame,
    overloaded: list[int],
    scale: float,
) -> pd.DataFrame:
    """Simulate the leads for one (intake, city) pair, before the funnel."""
    gen = assumptions["generator"]
    gt = gen["ground_truth"]
    _, _, _, lead_share, (rent_low, rent_high) = ref.CITIES[city.city]
    n = int(
        rng.poisson(
            gen["leads_per_intake_unit"] * scale * gen["intake_volume"][intake.intake] * lead_share
        )
    )
    country = rng.choice(ref.SOURCE_COUNTRIES, size=n, p=ref.SOURCE_MIX_BY_MARKET[city.country])
    is_pg = rng.random(n) < pd.Series(country).map(ref.PG_SHARE).to_numpy()
    keep_prob = _pg_keep_probability(gt, intake.academic_year, city.city, city.country)
    keep = ~is_pg | (rng.random(n) < keep_prob)

    intake_start = pd.Timestamp(intake.intake_start_date)
    created = _created_at(rng, n, gt["e8_lead_seasonality"][intake.intake_month], intake_start)

    group = pd.Series(country).map(ref.COUNTRY_GROUP).fillna(ref.DEFAULT_COUNTRY_GROUP)
    channel_probs = np.array([ref.CHANNEL_MIX_BY_GROUP[g] for g in group], dtype=float).reshape(
        n, len(ref.CHANNELS)
    )
    channel = np.array(ref.CHANNELS)[sample_categorical(rng.random(n), channel_probs)]

    city_unis = universities.loc[universities["city_id"] == city.city_id, "university_id"]
    university = rng.choice(city_unis.to_numpy(), size=n)

    typical_rent_gbp = (rent_low + rent_high) / 2 * city.fx_to_gbp
    budget = (
        typical_rent_gbp
        * pd.Series(country).map(ref.BUDGET_FACTOR).to_numpy()
        * np.exp(rng.normal(0.0, ref.BUDGET_SIGMA, size=n))
    )
    guarantor_p = pd.Series(country).map(ref.GUARANTOR_PROB).fillna(ref.DEFAULT_GUARANTOR_PROB)
    visa_p = pd.Series(country).map(ref.VISA_REQUIRED_PROB[city.country]).fillna(1.0)

    team = next(t for t, (cities, _, _) in ref.TEAMS.items() if city.city in cities)
    team_agents = agents.loc[agents["team"] == team, "agent_id"].to_numpy()
    weight = np.where(
        np.isin(team_agents, overloaded), gt["e7_overloaded_agents"]["assignment_weight"], 1.0
    )
    agent = rng.choice(team_agents, size=n, p=weight / weight.sum())

    block = pd.DataFrame(
        {
            "created_at": created,
            "channel": channel,
            "intake": intake.intake,
            "city_id": city.city_id,
            "agent_id": agent,
            "source_country": country,
            "level": np.where(is_pg, "PG", "UG"),
            "university_id": university,
            "budget_weekly_gbp": np.round(budget, 2),
            "has_guarantor": rng.random(n) < guarantor_p.to_numpy(),
            "visa_required": rng.random(n) < visa_p.to_numpy(),
            "_intake_order": intake.sort_order,
            "_intake_month": intake.intake_month,
            "_intake_start": intake_start,
            "_intake_closed": intake.is_closed,
            "_market": city.country,
            "_city": city.city,
        }
    )
    return block.loc[keep]


def _assign_repeat_students(rng: np.random.Generator, leads: pd.DataFrame, share: float) -> None:
    """A few students enquire again for a later intake in the same city: reuse their student row."""
    leads["student_id"] = leads["lead_id"].to_numpy()
    is_repeat = (leads["_intake_order"].to_numpy() > 1) & (rng.random(len(leads)) < share)
    for (city_id, order), idx in (
        leads.loc[is_repeat].groupby(["city_id", "_intake_order"]).groups.items()
    ):
        pool = leads.index[
            (leads["city_id"] == city_id) & (leads["_intake_order"] < order) & ~is_repeat
        ]
        originals = rng.choice(pool.to_numpy(), size=len(idx))
        for col in ["student_id", *STUDENT_COLUMNS]:
            leads.loc[idx, col] = leads.loc[originals, col].to_numpy()


def _run_funnel(
    rng: np.random.Generator,
    assumptions: dict[str, Any],
    leads: pd.DataFrame,
    overloaded: list[int],
    snapshot: pd.Timestamp,
) -> pd.DataFrame:
    """Contact → shortlist → book, with effects 4 (slow response), 5 (channel) and 7 (overload)."""
    gt = assumptions["generator"]["ground_truth"]
    late_minutes = assumptions["operations"]["late_first_response_minutes"]
    n = len(leads)
    created = leads["created_at"]
    start = leads["_intake_start"]
    is_overloaded = leads["agent_id"].isin(overloaded).to_numpy()

    contacted = rng.random(n) >= ref.NEVER_CONTACTED_SHARE
    minutes = np.exp(
        rng.normal(np.log(ref.RESPONSE_MEDIAN_MINUTES), ref.RESPONSE_SIGMA, size=n)
    ) * np.where(is_overloaded, gt["e7_overloaded_agents"]["response_time_multiplier"], 1.0)
    minutes = np.clip(np.round(minutes), 1, ref.RESPONSE_MAX_MINUTES).astype(int)
    contacted_at = created + pd.to_timedelta(minutes, unit="m")

    slow = minutes > late_minutes
    channel_effect = leads["channel"].map(gt["e5_channel_logit"]).to_numpy()
    shortlist_logit = (
        ref.SHORTLIST_BASE_LOGIT
        + 0.5 * channel_effect
        + np.where(slow, gt["e4_slow_response"]["shortlist_logit"], 0.0)
        - 0.1 * np.log1p(minutes / 60.0)
        + rng.normal(0.0, ref.FUNNEL_LOGIT_NOISE, size=n)
    )
    book_logit = (
        ref.BOOK_BASE_LOGIT
        + 0.5 * channel_effect
        + np.where(slow, gt["e4_slow_response"]["booking_logit"], 0.0)
        + rng.normal(0.0, ref.FUNNEL_LOGIT_NOISE, size=n)
    )
    shortlisted = contacted & (rng.random(n) < sigmoid(shortlist_logit))
    shortlisted_at = contacted_at + days(rng.exponential(ref.DAYS_TO_SHORTLIST_MEAN, size=n))
    booked = shortlisted & (rng.random(n) < sigmoid(book_logit))
    booked_at = shortlisted_at + days(rng.exponential(ref.DAYS_TO_BOOK_MEAN, size=n))
    squeeze = rng.random(n)
    loss_delay = days(rng.exponential(ref.DAYS_TO_LOSS_MEAN, size=n))

    # Rooms must be booked at least a day before move-in; late shortlists cannot book.
    latest_booking = start - pd.Timedelta(days=1)
    shortlisted &= (shortlisted_at < start).to_numpy()
    booked &= (shortlisted_at < latest_booking).to_numpy()
    too_late = (booked_at > latest_booking).to_numpy()
    booked_at = booked_at.where(
        ~too_late, shortlisted_at + (latest_booking - shortlisted_at) * squeeze
    )
    last_event = shortlisted_at.where(shortlisted, contacted_at.where(contacted, created))
    lost_at = last_event + loss_delay

    # Censor at the snapshot date.
    contacted_obs = contacted & (contacted_at <= snapshot).to_numpy()
    shortlisted_obs = shortlisted & (shortlisted_at <= snapshot).to_numpy()
    booked_obs = booked & (booked_at <= snapshot).to_numpy()
    lost_obs = ~booked & (leads["_intake_closed"].to_numpy() | (lost_at <= snapshot).to_numpy())

    status = np.select(
        [booked_obs, lost_obs, shortlisted_obs, contacted_obs],
        ["booked", "lost", "shortlisted", "contacted"],
        default="new",
    )
    furthest = np.select([shortlisted_obs, contacted_obs], ["shortlisted", "contacted"], "new")
    lost_reason = np.full(n, None, dtype=object)
    for stage, (reasons, probs) in ref.LOST_REASONS.items():
        mask = lost_obs & (furthest == stage)
        lost_reason[mask] = rng.choice(reasons, size=int(mask.sum()), p=probs)

    leads["first_response_minutes"] = pd.Series(minutes, dtype="Int64").where(contacted_obs)
    leads["contacted_at"] = contacted_at.where(contacted_obs)
    leads["shortlisted_at"] = shortlisted_at.where(shortlisted_obs)
    leads["status"] = status
    leads["lost_reason"] = lost_reason
    leads["_overloaded"] = is_overloaded
    leads["_booked_at"] = booked_at.where(booked_obs)
    # When the lead's pre-booking conversation really ends, even if that is after the snapshot.
    # Interaction timestamps are spread over this full window and censored later (ADR-015).
    leads["_lead_end"] = booked_at.where(booked, lost_at).where(contacted_obs)
    return leads


def build_students_and_leads(
    rng: np.random.Generator,
    assumptions: dict[str, Any],
    intakes: pd.DataFrame,
    cities: pd.DataFrame,
    universities: pd.DataFrame,
    agents: pd.DataFrame,
    overloaded: list[int],
    scale: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (dim_student, leads). `leads` keeps internal `_`-prefixed columns for later stages."""
    snapshot = pd.Timestamp(assumptions["project"]["snapshot_date"])
    blocks = [
        _lead_block(rng, assumptions, intake, city, universities, agents, overloaded, scale)
        for intake in intakes.itertuples(index=False)
        for city in cities.itertuples(index=False)
    ]
    leads = pd.concat(blocks, ignore_index=True)
    leads = leads.loc[leads["created_at"] <= snapshot]
    leads = leads.sort_values("created_at", kind="mergesort").reset_index(drop=True)
    leads.insert(0, "lead_id", np.arange(1, len(leads) + 1, dtype=np.int64))

    _assign_repeat_students(rng, leads, assumptions["generator"]["repeat_student_share"])
    leads = _run_funnel(rng, assumptions, leads, overloaded, snapshot)

    students = (
        leads.loc[leads["student_id"] == leads["lead_id"], ["student_id", *STUDENT_COLUMNS]]
        .reset_index(drop=True)
        .astype({"student_id": "int64", "university_id": "int64", "has_guarantor": bool})
    )
    leads = leads.astype({"student_id": "int64", "university_id": "int64", "visa_required": bool})
    return students, leads
