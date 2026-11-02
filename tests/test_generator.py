"""Generator: determinism, volumes, speed, snapshot censoring and schema."""

import pandas as pd
import pytest

from stayguard.config import load_assumptions
from stayguard.generate.pipeline import TABLE_ORDER, generate

SMALL = 0.05


def test_generator_is_deterministic():
    first = generate(scale=SMALL)
    second = generate(scale=SMALL)
    for name in TABLE_ORDER:
        pd.testing.assert_frame_equal(first.tables[name], second.tables[name], obj=name)
    assert first.manifest["fingerprints"] == second.manifest["fingerprints"]


def test_different_seed_gives_different_data():
    a = generate(scale=SMALL)
    b = generate(seed=a.manifest["seed"] + 1, scale=SMALL)
    assert a.manifest["fingerprints"]["fact_booking"] != b.manifest["fingerprints"]["fact_booking"]


def test_volumes_near_targets(generated):
    volumes = load_assumptions()["volumes"]
    counts = generated.manifest["row_counts"]
    assert counts["fact_lead"] == pytest.approx(volumes["leads_target"], rel=0.05)
    assert counts["fact_booking"] == pytest.approx(volumes["bookings_target"], rel=0.05)


def test_generation_is_fast_enough(generated):
    limit = load_assumptions()["volumes"]["max_generation_seconds"]
    assert generated.manifest["generation_seconds"] < limit


def test_tables_load_with_declared_schema(con):
    loaded = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    assert set(TABLE_ORDER) <= loaded
    for name in TABLE_ORDER:
        assert con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] > 0, name


def test_no_event_after_snapshot(generated):
    snapshot = pd.Timestamp(generated.manifest["snapshot_date"])
    t = generated.tables
    assert t["fact_lead"]["created_at"].max() <= snapshot
    assert t["fact_booking"]["booked_at"].max() <= snapshot
    assert t["fact_cancellation"]["cancelled_at"].max() <= snapshot
    assert t["fact_interaction"]["ts"].max() <= snapshot


def test_status_matches_intake_state(generated):
    t = generated.tables
    closed = set(t["dim_intake"].loc[t["dim_intake"]["is_closed"], "intake"])
    bookings, leads = t["fact_booking"], t["fact_lead"]
    assert set(bookings.loc[bookings["intake"].isin(closed), "status"]) == {"cancelled", "moved_in"}
    assert set(bookings.loc[~bookings["intake"].isin(closed), "status"]) == {"cancelled", "open"}
    assert set(leads.loc[leads["intake"].isin(closed), "status"]) == {"booked", "lost"}


def test_university_names_are_fictional(generated):
    names = generated.tables["dim_university"]["name"]
    assert not names.str.contains("University of ", regex=False).any()


def test_no_brand_name_in_any_generated_text(generated):
    """Branding rule (CLAUDE.md §0): the marketplace's name must not appear anywhere in the data."""
    for name, df in generated.tables.items():
        for col in df.select_dtypes(include=["object", "string"]).columns:
            hits = df[col].astype(str).str.contains("amber", case=False)
            assert not hits.any(), f"{name}.{col}: {df.loc[hits, col].head(3).tolist()}"
