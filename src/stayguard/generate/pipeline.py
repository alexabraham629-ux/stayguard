"""Orchestrates the generator: seeded streams → tables → planted issues → manifest."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from stayguard.config import load_assumptions
from stayguard.generate.bookings import BOOKING_COLUMNS, CANCELLATION_COLUMNS, build_bookings
from stayguard.generate.data_issues import plant_all
from stayguard.generate.dimensions import (
    build_agents,
    build_cities,
    build_intakes,
    build_properties,
    build_universities,
)
from stayguard.generate.interactions import build_interactions
from stayguard.generate.leads import build_students_and_leads

GENERATOR_VERSION = "1.0"

# Load order respects foreign keys.
TABLE_ORDER: tuple[str, ...] = (
    "dim_intake",
    "dim_city",
    "dim_university",
    "dim_property",
    "dim_agent",
    "dim_student",
    "fact_lead",
    "fact_booking",
    "fact_cancellation",
    "fact_interaction",
)
LEAD_COLUMNS = [
    "lead_id",
    "student_id",
    "created_at",
    "channel",
    "intake",
    "city_id",
    "first_response_minutes",
    "contacted_at",
    "shortlisted_at",
    "agent_id",
    "status",
    "lost_reason",
]
STUDENT_COLUMNS = [
    "student_id",
    "source_country",
    "level",
    "university_id",
    "budget_weekly_gbp",
    "has_guarantor",
]
STREAMS = ("dimensions", "leads", "bookings", "interactions", "data_issues")
SAMPLE_ROWS = 200


@dataclass(frozen=True)
class GeneratedData:
    """Public tables plus a manifest: row counts, planted issues, ground truth, fingerprints."""

    tables: dict[str, pd.DataFrame]
    manifest: dict[str, Any]
    # The future outcome of each open booking (booking_id, will_cancel). Only knowable because the
    # data is synthetic; kept in memory for the model's oracle test, never written to disk or DB.
    hidden_truth: pd.DataFrame = field(default_factory=pd.DataFrame, repr=False)


def fingerprint(df: pd.DataFrame) -> str:
    """Stable hash of a table's content, used by the determinism test."""
    hashed = pd.util.hash_pandas_object(df, index=False).to_numpy()
    return hashlib.sha256(hashed.tobytes()).hexdigest()[:16]


def generate(seed: int | None = None, scale: float = 1.0) -> GeneratedData:
    """Generate every table deterministically from `seed` (default: assumptions.yaml)."""
    started = time.perf_counter()
    assumptions = load_assumptions()
    seed = int(assumptions["project"]["seed"] if seed is None else seed)
    # Independent random stream per stage: changing one stage does not reshuffle the others.
    rngs = dict(
        zip(
            STREAMS,
            (np.random.default_rng(s) for s in np.random.SeedSequence(seed).spawn(len(STREAMS))),
            strict=True,
        )
    )
    gt = assumptions["generator"]["ground_truth"]

    intakes = build_intakes(assumptions)
    cities = build_cities(assumptions)
    universities = build_universities(rngs["dimensions"], cities)
    properties = build_properties(rngs["dimensions"], cities)
    agents, overloaded = build_agents(rngs["dimensions"], seed, gt["e7_overloaded_agents"])
    students, leads = build_students_and_leads(
        rngs["leads"], assumptions, intakes, cities, universities, agents, overloaded, scale
    )
    bookings, cancellations = build_bookings(
        rngs["bookings"], assumptions, leads, properties, cities
    )
    interactions = build_interactions(rngs["interactions"], assumptions, leads, bookings)
    hidden_truth = bookings.loc[
        bookings["status"] == "open", ["booking_id", "_will_cancel"]
    ].rename(columns={"_will_cancel": "will_cancel"})
    bookings, cancellations, planted = plant_all(
        rngs["data_issues"], assumptions, leads, bookings, cancellations
    )

    tables = {
        "dim_intake": intakes,
        "dim_city": cities,
        "dim_university": universities,
        "dim_property": properties,
        "dim_agent": agents,
        "dim_student": students[STUDENT_COLUMNS],
        "fact_lead": leads[LEAD_COLUMNS],
        "fact_booking": bookings[BOOKING_COLUMNS],
        "fact_cancellation": cancellations[CANCELLATION_COLUMNS],
        "fact_interaction": interactions,
    }
    tables = {name: tables[name].reset_index(drop=True) for name in TABLE_ORDER}
    manifest = {
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "scale": scale,
        "snapshot_date": str(assumptions["project"]["snapshot_date"]),
        "row_counts": {name: len(df) for name, df in tables.items()},
        "planted_issues": planted,
        "ground_truth": {"overloaded_agent_ids": overloaded},
        "fingerprints": {name: fingerprint(df) for name, df in tables.items()},
        "generation_seconds": round(time.perf_counter() - started, 2),
    }
    return GeneratedData(
        tables=tables, manifest=manifest, hidden_truth=hidden_truth.reset_index(drop=True)
    )


def write_raw(data: GeneratedData, raw_dir: Path) -> None:
    """Write every table as CSV, a small committed sample, and the manifest."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    sample_dir = raw_dir / "sample"
    sample_dir.mkdir(exist_ok=True)
    for name, df in data.tables.items():
        # LF line endings so CSVs are byte-identical on Windows and macOS.
        df.to_csv(raw_dir / f"{name}.csv", index=False, lineterminator="\n")
        df.head(SAMPLE_ROWS).to_csv(sample_dir / f"{name}.csv", index=False, lineterminator="\n")
    (raw_dir / "manifest.json").write_text(json.dumps(data.manifest, indent=2), encoding="utf-8")
