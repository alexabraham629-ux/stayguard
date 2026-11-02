"""Quality report and shared views: planted issues are caught exactly, integrity rules hold."""

import pytest

from stayguard.quality.checks import run_quality_report
from tests.conftest import scalar


@pytest.fixture(scope="module")
def report(con):
    return run_quality_report(con).set_index("check_id")


def test_integrity_checks_all_pass(report):
    integrity = report[report["category"] == "integrity"]
    assert len(integrity) >= 15
    failed = integrity[integrity["result"] != "PASS"]
    assert failed.empty, failed[["check_name", "failing_rows"]].to_string()


def test_planted_issues_detected_exactly(report, generated):
    planted = generated.manifest["planted_issues"]
    assert report.loc["P1", "failing_rows"] == planted["duplicate_booking_rows"]
    assert report.loc["P2", "failing_rows"] == planted["null_first_response_minutes"]
    assert report.loc["P3", "failing_rows"] == planted["cancelled_before_booked"]
    assert report.loc["P4", "failing_rows"] == planted["non_gbp_bookings"]
    assert (report.loc[["P1", "P2", "P3", "P4"], "result"] == "DETECTED").all()


def test_clean_view_removes_only_the_duplicate_rows(con, generated):
    raw = scalar(con, "SELECT COUNT(*) FROM fact_booking")
    clean = scalar(con, "SELECT COUNT(*) FROM v_clean_bookings")
    assert raw - clean == generated.manifest["planted_issues"]["duplicate_booking_rows"]
    # Business cancellations with reason 'duplicate_booking' must survive cleaning (ADR-008).
    assert (
        scalar(con, "SELECT COUNT(*) FROM v_bookings_gbp WHERE cancel_reason = 'duplicate_booking'")
        > 0
    )


def test_bookings_gbp_has_one_row_per_clean_booking(con):
    assert scalar(con, "SELECT COUNT(*) FROM v_bookings_gbp") == scalar(
        con, "SELECT COUNT(*) FROM v_clean_bookings"
    )


def test_gbp_conversion_differs_from_naive_local_sum(con):
    """Guard against the mixed-currency bug: summing local amounts across countries is wrong."""
    converted = scalar(con, "SELECT SUM(gbv_gbp) FROM v_bookings_gbp")
    naive = float(scalar(con, "SELECT SUM(gbv_local) FROM v_bookings_gbp"))
    by_hand = scalar(
        con,
        """SELECT SUM(b.gbv_local * c.fx_to_gbp)
           FROM v_clean_bookings b JOIN dim_property p USING (property_id)
           JOIN dim_city c ON c.city_id = p.city_id""",
    )
    assert converted == pytest.approx(by_hand, rel=1e-9)
    assert abs(naive - converted) / converted > 0.05
