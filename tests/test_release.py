"""Release checks: first-boot build, star-schema export, dependency files."""

import duckdb
import pytest

from stayguard.bootstrap import ensure_database
from stayguard.export import STAR_SCHEMA, export_star_schema
from stayguard.metrics import (
    booked_commission_gbp,
    expected_net_commission_gbp,
    load_metric_data,
    revenue_at_risk_gbp,
)


def test_first_boot_builds_a_complete_database(tmp_path):
    db = tmp_path / "fresh.duckdb"
    assert ensure_database(db) is True
    assert ensure_database(db) is False  # second call is a no-op
    assert not list(tmp_path.glob("*.building.duckdb"))  # no partial file left behind
    with duckdb.connect(str(db), read_only=True) as con:
        version = con.execute("SELECT DISTINCT model_version FROM scored_bookings").fetchall()
        assert version and version[0][0] != "baseline_segment_rate_v1"  # the model scored it
        assert con.execute("SELECT COUNT(*) FROM v_bookings_gbp").fetchone()[0] > 15_000


@pytest.fixture(scope="module")
def exported(con, tmp_path_factory):
    out = tmp_path_factory.mktemp("exports")
    return out, export_star_schema(con, out)


def test_export_writes_csv_and_parquet_for_every_table(exported):
    out, counts = exported
    assert set(counts) == set(STAR_SCHEMA)
    for name in STAR_SCHEMA:
        assert (out / f"{name}.csv").exists() and (out / f"{name}.parquet").exists()


def test_exported_facts_reconcile_with_metrics(exported, con):
    out, _ = exported
    data = load_metric_data(con)
    totals = (
        duckdb.connect()
        .execute(
            f"""SELECT SUM(commission_gbp), SUM(expected_net_commission_gbp), SUM(revenue_at_risk_gbp)
            FROM '{(out / "fact_bookings.parquet").as_posix()}'"""
        )
        .fetchone()
    )
    assert totals[0] == pytest.approx(booked_commission_gbp(data), rel=1e-9)
    assert totals[1] == pytest.approx(expected_net_commission_gbp(data), rel=1e-9)
    assert totals[2] == pytest.approx(revenue_at_risk_gbp(data), rel=1e-9)


def test_date_dimension_covers_every_fact_date(exported):
    out, _ = exported
    missing = (
        duckdb.connect()
        .execute(
            f"""SELECT COUNT(*) FROM '{(out / "fact_bookings.parquet").as_posix()}' f
            ANTI JOIN '{(out / "dim_date.parquet").as_posix()}' d ON d.date = f.booked_date"""
        )
        .fetchone()[0]
    )
    assert missing == 0
