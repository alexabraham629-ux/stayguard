"""Dimension tables: intakes, cities, universities, properties and agents."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from faker import Faker

from stayguard.generate import reference as ref


def academic_year(intake: str) -> str:
    """'Sep-2025' and 'Jan-2026' both belong to academic year '2025-26'."""
    month, year = intake.split("-")
    start = int(year) if month == "Sep" else int(year) - 1
    return f"{start}-{(start + 1) % 100:02d}"


def build_intakes(assumptions: dict[str, Any]) -> pd.DataFrame:
    """One row per intake with its move-in date and whether it had started by the snapshot."""
    snapshot = pd.Timestamp(assumptions["project"]["snapshot_date"])
    rows = []
    for order, (intake, start) in enumerate(assumptions["intakes"].items(), start=1):
        start_ts = pd.Timestamp(start)
        rows.append(
            {
                "intake": intake,
                "intake_start_date": start_ts.date(),
                "intake_month": intake.split("-")[0],
                "academic_year": academic_year(intake),
                "is_closed": bool(start_ts <= snapshot),
                "sort_order": order,
            }
        )
    return pd.DataFrame(rows)


def build_cities(assumptions: dict[str, Any]) -> pd.DataFrame:
    """The 12 markets, with the fixed FX rate used to convert to GBP (ADR-009)."""
    fx = assumptions["currency"]["fx_to_gbp"]
    rows = [
        {
            "city_id": city_id,
            "city": city,
            "country": country,
            "currency": currency,
            "market_tier": tier,
            "fx_to_gbp": float(fx[currency]),
        }
        for city_id, (city, (country, currency, tier, _, _)) in enumerate(
            ref.CITIES.items(), start=1
        )
    ]
    return pd.DataFrame(rows)


def build_universities(rng: np.random.Generator, cities: pd.DataFrame) -> pd.DataFrame:
    """Fictional universities, two or three per city."""
    rows = []
    for city in cities.itertuples(index=False):
        low, high = (0.35, 0.55) if city.market_tier == 1 else (0.20, 0.40)
        for name in ref.UNIVERSITIES[city.city]:
            rows.append(
                {
                    "name": name,
                    "city_id": city.city_id,
                    "intl_share": round(float(rng.uniform(low, high)), 3),
                }
            )
    df = pd.DataFrame(rows)
    df.insert(0, "university_id", np.arange(1, len(df) + 1))
    return df


def build_properties(rng: np.random.Generator, cities: pd.DataFrame) -> pd.DataFrame:
    """Rooms on the marketplace: operator type, room type, rent, cancellation policy, quality."""
    operators = list(ref.OPERATOR_MIX)
    frames = []
    for city in cities.itertuples(index=False):
        _, _, _, lead_share, (rent_low, rent_high) = ref.CITIES[city.city]
        n = int(round(ref.PROPERTIES_BASE_PER_CITY + ref.PROPERTIES_PER_LEAD_SHARE * lead_share))
        operator = rng.choice(operators, size=n, p=list(ref.OPERATOR_MIX.values()))
        room = np.array(
            [
                rng.choice(list(ref.ROOM_MIX[op]), p=list(ref.ROOM_MIX[op].values()))
                for op in operator
            ]
        )
        base_rent = rng.uniform(rent_low, rent_high, size=n)
        rent = (
            base_rent
            * pd.Series(room).map(ref.ROOM_RENT_FACTOR).to_numpy()
            * pd.Series(operator).map(ref.OPERATOR_RENT_FACTOR).to_numpy()
            * np.exp(rng.normal(0.0, 0.08, size=n))
        )
        nvnp_prob = pd.Series(operator).map(ref.NO_VISA_NO_PAY_PROB).to_numpy()
        cooling = np.array(
            [rng.choice(ref.COOLING_OFF_OPTIONS, p=ref.COOLING_OFF_PROBS[op]) for op in operator]
        )
        frames.append(
            pd.DataFrame(
                {
                    "city_id": city.city_id,
                    "operator_type": operator,
                    "room_type": room,
                    "weekly_rent_local": np.round(rent, 2),
                    "has_no_visa_no_pay": rng.random(n) < nvnp_prob,
                    "cooling_off_days": cooling.astype(int),
                    "distance_km_to_university": np.round(rng.gamma(2.0, 1.2, size=n), 2),
                    "rating": np.round(np.clip(rng.normal(4.2, 0.35, size=n), 2.5, 5.0), 1),
                }
            )
        )
    df = pd.concat(frames, ignore_index=True)
    df.insert(0, "property_id", np.arange(1, len(df) + 1))
    return df


def _agent_name(fake: Faker) -> str:
    """Faker name, never containing a reserved brand word (CLAUDE.md branding rule)."""
    while True:
        name = f"{fake.first_name()} {fake.last_name()}"
        if not any(word.lower() in name.lower() for word in ref.RESERVED_NAME_WORDS):
            return name


def build_agents(
    rng: np.random.Generator, seed: int, overload: dict[str, Any]
) -> tuple[pd.DataFrame, list[int]]:
    """Booking managers by team; also returns the ids of the overloaded agents (effect 7)."""
    fakers: dict[str, Faker] = {}
    rows = []
    for team, (_, n_agents, locales) in ref.TEAMS.items():
        for _ in range(n_agents):
            locale = str(rng.choice(locales))
            if locale not in fakers:
                fakers[locale] = Faker(locale)
                fakers[locale].seed_instance(seed + len(fakers))
            fake = fakers[locale]
            extra = rng.choice(ref.AGENT_LANGUAGES, size=int(rng.integers(0, 3)), replace=False)
            rows.append(
                {
                    "agent_name": _agent_name(fake),
                    "team": team,
                    "languages": ", ".join(["English", *sorted(extra)]),
                    "hire_date": (
                        pd.Timestamp("2019-01-01") + pd.Timedelta(days=int(rng.integers(0, 1600)))
                    ).date(),
                    "max_daily_capacity": int(rng.integers(*ref.AGENT_CAPACITY_RANGE)),
                }
            )
    df = pd.DataFrame(rows)
    df.insert(0, "agent_id", np.arange(1, len(df) + 1))
    candidates = df.loc[df["team"].isin(ref.OVERLOAD_CANDIDATE_TEAMS), "agent_id"].to_numpy()
    overloaded = sorted(
        int(a) for a in rng.choice(candidates, size=overload["count"], replace=False)
    )
    low, high = overload["capacity_range"]
    df.loc[df["agent_id"].isin(overloaded), "max_daily_capacity"] = rng.integers(
        low, high + 1, size=len(overloaded)
    )
    return df, overloaded
