"""SQL library: every query runs, follows the house rules, and reconciles with metrics.py.

metrics.py computes in pandas, independently of the SQL, so agreement here means two different
implementations of each definition give the same number.
"""

import re

import pandas as pd
import pytest

from stayguard.calendar import days_to_open_intake, open_intake
from stayguard.config import PROJECT_ROOT, load_assumptions
from stayguard.metrics import (
    Filters,
    agent_load,
    booked_commission_gbp,
    cancellation_rate,
    expected_net_commission_gbp,
    lead_to_booking_conversion,
    live_commission_loss_share,
    load_metric_data,
    realised_commission_gbp,
    revenue_at_risk_gbp,
    saveable_revenue_gbp,
    weekly_cancellation_rates,
)
from stayguard.sql_runner import HEADER_KEYS, list_queries, load_sql, parse_header, run_query

TOLERANCE = load_assumptions()["ai"]["verification_tolerance"]  # 0.5% relative
QUERIES = list_queries()


@pytest.fixture(scope="module")
def data(con):
    return load_metric_data(con)


@pytest.fixture(scope="module")
def q(con):
    cache: dict[str, pd.DataFrame] = {}

    def run(name: str) -> pd.DataFrame:
        if name not in cache:
            cache[name] = run_query(con, name)
        return cache[name]

    return run


def closed(df: pd.DataFrame) -> pd.DataFrame:
    return df.loc[df["is_closed_intake"]]


# --- House rules for every file -----------------------------------------------------------------


def test_library_is_numbered_without_gaps():
    """The 14 required queries plus the app's additions, numbered 01..N with no gaps."""
    assert len(QUERIES) >= 14
    assert [name[:2] for name in QUERIES] == [f"{i:02d}" for i in range(1, len(QUERIES) + 1)]


@pytest.mark.parametrize("name", QUERIES)
def test_query_has_header_and_runs(name, q):
    header = parse_header(name)
    assert set(HEADER_KEYS) <= set(header), (
        f"{name} header missing {set(HEADER_KEYS) - set(header)}"
    )
    assert header["name"] == name
    assert len(q(name)) > 0


@pytest.mark.parametrize("name", QUERIES)
def test_validated_by_points_to_a_real_test(name):
    target = parse_header(name)["validated_by"]
    path, _, function = target.partition("::")
    test_file = PROJECT_ROOT / path
    assert test_file.exists(), target
    assert f"def {function}(" in test_file.read_text(encoding="utf-8"), target


@pytest.mark.parametrize("name", QUERIES)
def test_final_select_lists_columns(name):
    """No SELECT * in the final select (CTEs may use it). Final selects start at column 0."""
    sql = re.sub(r"--[^\n]*", "", load_sql(name))
    first_final = re.search(r"^SELECT\b", sql, flags=re.MULTILINE)
    assert first_final, f"{name}: no top-level SELECT"
    assert not re.search(r"(SELECT|,)\s*(\w+\.)?\*", sql[first_final.start() :]), name


# --- Reconciliation, one test per query ---------------------------------------------------------


def test_funnel_matches_metrics(q, data):
    df = q("01_funnel_by_city_intake")
    assert df["leads"].sum() == len(data.leads)
    closed_rows = closed(df)
    sql_rate = closed_rows["booked"].sum() / closed_rows["leads"].sum()
    assert sql_rate == pytest.approx(lead_to_booking_conversion(data), rel=1e-12)
    london = closed_rows.loc[closed_rows["city"] == "London"]
    assert london["booked"].sum() / london["leads"].sum() == pytest.approx(
        lead_to_booking_conversion(data, Filters(cities=("London",))), rel=1e-12
    )
    assert df["moved_in"].sum() == data.bookings["is_moved_in"].sum()
    assert (df["contacted"] >= df["shortlisted"]).all()
    assert (df["shortlisted"] >= df["booked"]).all()


def test_weekly_velocity_totals_and_lag(q, data):
    df = q("02_weekly_booking_velocity")
    assert df["bookings"].sum() == len(data.bookings)
    assert df["booked_commission_gbp"].sum() == pytest.approx(
        booked_commission_gbp(data), rel=TOLERANCE
    )
    weeks = pd.to_datetime(df["week_start"])
    assert (weeks.diff().dropna() == pd.Timedelta(days=7)).all(), "week spine has gaps"
    bookings = df["bookings"].astype(float)
    pd.testing.assert_series_equal(
        df["prev_week_bookings"].astype(float), bookings.shift(1), check_names=False
    )
    pd.testing.assert_series_equal(
        df["same_week_last_year_bookings"].astype(float), bookings.shift(52), check_names=False
    )


def test_cohort_curve_ends_at_cancellation_rate(q, data):
    df = q("03_cohort_cancellation_curve")
    for intake, curve in closed(df).groupby("intake"):
        curve = curve.sort_values("bucket_order")
        assert curve["cumulative_cancellations"].is_monotonic_increasing
        last = curve.iloc[-1]
        # Every cancellation is either in a timing bucket or excluded for an invalid timestamp.
        final_rate = (
            last["cumulative_cancellations"] + last["excluded_invalid_timestamps"]
        ) / last["cohort_bookings"]
        assert final_rate == pytest.approx(
            cancellation_rate(data, Filters(intakes=(intake,))), rel=1e-12
        ), intake


def test_pareto_running_share(q, data):
    df = q("04_cancellation_reasons_pareto").sort_values(["reason_rank", "cancel_reason"])
    assert df["cancellations"].sum() == closed(data.bookings)["is_cancelled"].sum()
    assert df["running_share_pct"].iloc[-1] == pytest.approx(100.0)
    assert df["running_share_pct"].is_monotonic_increasing
    assert df["in_vital_few"].iloc[0]
    vital = df.loc[df["in_vital_few"]]
    assert vital["share_pct"].sum() >= 80 - 0.1 * len(vital)  # rounding slack per row


def test_rolling_cancellation_matches_metrics(q, data):
    df = q("05_rolling_cancellation_rate")
    for city in ("London", "Brisbane"):
        sql = df.loc[df["city"] == city].reset_index(drop=True)
        expected = weekly_cancellation_rates(data, city)
        assert len(sql) == len(expected)
        assert (pd.to_datetime(sql["week_start"]) == expected["week_start"]).all()
        pd.testing.assert_series_equal(
            sql["rolling_4wk_pooled_rate_pct"].astype(float) / 100,
            expected["rolling_4wk_pooled_rate"],
            check_names=False,
            atol=1e-4,  # SQL rounds the percentage to 2 decimals
        )


def test_agent_leaderboard_matches_metrics(q, data, generated):
    df = q("06_agent_leaderboard").set_index("agent_id")
    load = agent_load(data)
    pd.testing.assert_series_equal(
        df["load_days"].sort_index(),
        load.round(2).sort_index(),
        check_names=False,
        check_index_type=False,
        atol=0.006,
    )
    overloaded = generated.manifest["ground_truth"]["overloaded_agent_ids"]
    assert set(df.loc[df["load_rank"] <= 2].index) == set(overloaded)
    assert sorted(df["conversion_quartile"].value_counts().tolist()) == [7, 7, 7, 8]


def test_revenue_at_risk_matches_metrics(q, data):
    df = q("07_revenue_at_risk_by_city")
    assert df["expected_net_commission_gbp"].sum() == pytest.approx(
        expected_net_commission_gbp(data), rel=TOLERANCE
    )
    assert df["revenue_at_risk_gbp"].sum() == pytest.approx(
        revenue_at_risk_gbp(data), rel=TOLERANCE
    )
    london = df.loc[df["city"] == "London", "revenue_at_risk_gbp"].item()
    assert london == pytest.approx(
        revenue_at_risk_gbp(data, Filters(cities=("London",))), rel=TOLERANCE
    )
    assert df["share_of_total_risk_pct"].sum() == pytest.approx(100, abs=0.1 * len(df))
    open_commission = data.bookings.loc[data.bookings["is_open"], "commission_gbp"].sum()
    assert (df["expected_net_commission_gbp"] + df["revenue_at_risk_gbp"]).sum() == pytest.approx(
        open_commission, rel=TOLERANCE
    )


def test_response_buckets_reconcile(q, data):
    df = q("08_response_time_vs_conversion")
    leads = closed(data.leads)
    leads = leads.loc[leads["first_response_minutes"].notna()]
    assert df["leads"].sum() == len(leads)
    assert df["booked"].sum() == (leads["status"] == "booked").sum()
    shares = df["leads"] / df["leads"].sum()
    assert shares.between(0.17, 0.23).all(), "quintiles should be roughly equal-sized"
    assert (
        df.loc[df["quintile"] == 5, "conversion_pct"].item()
        < df.loc[df["quintile"] == 1, "conversion_pct"].item()
    )


def test_visa_risk_matches_pandas(q, data):
    df = q("09_source_country_visa_risk").set_index(["source_country", "visa_status_at_booking"])
    b = closed(data.bookings)
    expected = b.groupby(["source_country", "visa_status_at_booking"]).agg(
        bookings=("booking_id", "size"),
        cancellations=("is_cancelled", "sum"),
        visa_refusals=("cancel_reason", lambda s: (s == "visa_refused").sum()),
    )
    pd.testing.assert_frame_equal(
        df[["bookings", "cancellations", "visa_refusals"]].sort_index(),
        expected.sort_index(),
        check_dtype=False,
    )


def test_duplicate_detection_matches_quality_report(q, con):
    df = q("10_duplicate_booking_detection")
    flagged = set(df.loc[df["duplicate_kind"] == "data_entry_duplicate", "booking_id"])
    view_flags = {
        r[0]
        for r in con.execute(
            "SELECT booking_id FROM v_booking_duplicate_flags WHERE is_duplicate_row"
        ).fetchall()
    }
    assert flagged == view_flags  # self-join and LAG approaches agree
    quality = q("14_data_quality_report").set_index("check_id")
    assert len(flagged) == quality.loc["P1", "failing_rows"]
    business = df.loc[df["duplicate_kind"] == "business_duplicate_cancellation"]
    assert (
        len(business)
        == con.execute(
            "SELECT COUNT(*) FROM v_bookings_gbp WHERE cancel_reason = 'duplicate_booking'"
        ).fetchone()[0]
    )
    assert not flagged & set(business["booking_id"])


def test_yoy_pg_demand_matches_metrics(q, data):
    df = q("11_yoy_pg_demand_by_city")
    intakes = load_assumptions()["intakes"]
    snapshot = pd.Timestamp(load_assumptions()["project"]["snapshot_date"])
    open_start = min(pd.Timestamp(d) for d in intakes.values() if pd.Timestamp(d) > snapshot)
    days_left = (open_start - snapshot).days
    b = data.bookings
    like_for_like = b["intake"].str.startswith("Sep") | (
        b["days_booked_before_intake"] >= days_left
    )
    expected = (
        b.loc[(b["level"] == "PG") & like_for_like]
        .groupby(["city", "academic_year"])
        .size()
        .rename("pg_bookings")
    )
    sql = df.set_index(["city", "academic_year"])["pg_bookings"]
    pd.testing.assert_series_equal(
        sql.sort_index(), expected.reindex(sql.index, fill_value=0).sort_index(), check_dtype=False
    )
    seg = df.groupby(["segment", "academic_year"])["pg_bookings"].sum()
    assert seg["UK non-London"]["2025-26"] / seg["UK non-London"]["2024-25"] < 0.85


def test_channel_economics_matches_metrics(q, data):
    df = q("12_channel_unit_economics").set_index("channel")
    for channel, row in df.iterrows():
        f = Filters(channels=(channel,))
        assert row["conversion_pct"] == pytest.approx(
            100 * lead_to_booking_conversion(data, f), abs=0.05
        ), channel
        assert row["realised_commission_gbp"] == pytest.approx(
            realised_commission_gbp(data, f), rel=TOLERANCE
        ), channel
        assert row["cancellation_pct"] == pytest.approx(100 * cancellation_rate(data, f), abs=0.05)
    assert df["realised_commission_gbp"].sum() == pytest.approx(
        realised_commission_gbp(data), rel=TOLERANCE
    )


def test_action_queue_respects_capacity(q, data):
    df = q("13_action_queue")
    assert len(df) == data.bookings["is_open"].sum()
    assert df["priority_rank"].tolist() == list(range(1, len(df) + 1))
    assert df["expected_loss_gbp"].is_monotonic_decreasing
    today = df.loc[df["call_today"]].groupby("agent_id").size()
    capacity = df.groupby("agent_id")["max_daily_capacity"].first()
    assert (today <= capacity.reindex(today.index)).all()
    # Within each agent, the calls made today are that agent's highest-loss bookings.
    for _, agent_rows in df.groupby("agent_id"):
        called = agent_rows.loc[agent_rows["call_today"], "expected_loss_gbp"]
        waiting = agent_rows.loc[~agent_rows["call_today"], "expected_loss_gbp"]
        if len(called) and len(waiting):
            assert called.min() >= waiting.max()
    assert df["expected_loss_gbp"].sum() == pytest.approx(revenue_at_risk_gbp(data), rel=TOLERANCE)
    top_n = 100
    assert df.head(top_n)["saveable_if_called_gbp"].sum() == pytest.approx(
        saveable_revenue_gbp(data, top_n=top_n), rel=TOLERANCE
    )
    assert df["reason_codes"].str.len().gt(0).all()


def test_baseline_scores_cover_open_bookings_and_rank_risk(con, data):
    scores = con.execute("SELECT booking_id, p_cancel FROM scored_bookings_baseline").df()
    assert len(scores) == data.bookings["is_open"].sum()
    assert scores["p_cancel"].between(0, 1).all()
    open_b = data.bookings.loc[data.bookings["is_open"]].drop(columns="p_cancel")
    open_b = open_b.merge(scores, on="booking_id")
    risky = open_b.loc[
        open_b["visa_status_at_booking"].isin(["pending", "not_applied"]) & ~open_b["deposit_paid"],
        "p_cancel",
    ].mean()
    safe = open_b.loc[
        (open_b["visa_status_at_booking"] == "granted") & open_b["deposit_paid"], "p_cancel"
    ].mean()
    assert risky > safe


def test_commission_by_intake_matches_metrics(q, data):
    df = q("15_commission_by_intake").set_index("intake")
    days_left = days_to_open_intake(data.assumptions)
    for intake, row in df.iterrows():
        f = Filters(intakes=(intake,))
        assert row["booked_commission_gbp"] == pytest.approx(
            booked_commission_gbp(data, f), rel=1e-6
        )
        assert row["realised_commission_gbp"] == pytest.approx(
            realised_commission_gbp(data, f), rel=1e-6, abs=0.01
        )
        assert row["booked_commission_same_point_gbp"] == pytest.approx(
            booked_commission_gbp(data, f, min_days_before_intake=days_left), rel=1e-6
        )
        assert row["live_commission_loss_share"] == pytest.approx(
            live_commission_loss_share(data, Filters(), intake, days_left), rel=1e-6
        )
        if row["is_closed"]:
            assert row["cancellation_rate"] == pytest.approx(cancellation_rate(data, f))
            assert row["conversion_rate"] == pytest.approx(lead_to_booking_conversion(data, f))
    now = open_intake(data.assumptions)
    assert df.loc[now, "expected_net_commission_gbp"] == pytest.approx(
        expected_net_commission_gbp(data, Filters(intakes=(now,))), rel=1e-6
    )
    assert df.loc[now, "comparable_intake"] == "Jan-2026"


def test_budget_bands_reconcile(q, data):
    df = q("16_budget_band_vs_conversion")
    assert df["leads"].sum() == len(closed(data.leads))
    assert df["booked_leads"].sum() / df["leads"].sum() == pytest.approx(
        lead_to_booking_conversion(data), rel=1e-12
    )
    assert df["bookings"].sum() == len(closed(data.bookings))


def test_lead_seasonality_shares(q, data):
    df = q("17_lead_seasonality")
    assert df["leads"].sum() == len(data.leads)
    totals = df.groupby("intake")["share_of_intake_pct"].sum()
    assert ((totals - 100).abs() < 0.1).all()
    sep = df.loc[df["is_closed_intake"] & (df["intake_month"] == "Sep")]
    peak = sep.groupby("month_label")["share_of_intake_pct"].mean().idxmax()
    assert peak in {"Feb", "Mar", "Apr", "May", "Jun", "Jul"}
