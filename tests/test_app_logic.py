"""Business logic behind the app pages: executive KPIs, insights and the what-if simulator."""

import pytest

from stayguard.calendar import (
    comparable_intake,
    days_to_open_intake,
    latest_closed_intake,
    open_intake,
)
from stayguard.kpis import commission_by_intake, executive_kpis, headline_insights
from stayguard.metrics import (
    Filters,
    expected_net_commission_gbp,
    load_metric_data,
    saveable_revenue_gbp,
)
from stayguard.sim.whatif import WhatIfInputs, open_bookings, pipeline_stats, simulate
from stayguard.sql_runner import run_query


@pytest.fixture(scope="module")
def data(con):
    return load_metric_data(con)


def test_calendar_helpers(data):
    a = data.assumptions
    assert open_intake(a) == "Jan-2027"
    assert latest_closed_intake(a) == "Sep-2026"
    assert comparable_intake("Jan-2027") == "Jan-2026"
    assert days_to_open_intake(a) == 72


def test_executive_kpis_match_the_sql(con, data):
    kpis = {k.label: k for k in executive_kpis(data, Filters())}
    sql = run_query(con, "15_commission_by_intake").set_index("intake")
    assert kpis["Booked commission"].value == pytest.approx(
        sql.loc["Jan-2027", "booked_commission_gbp"], rel=1e-6
    )
    assert kpis["Booked commission"].delta == pytest.approx(
        sql.loc["Jan-2027", "booked_commission_gbp"]
        / sql.loc["Jan-2026", "booked_commission_same_point_gbp"]
        - 1,
        rel=1e-6,
    )
    assert kpis["Expected to land"].value == pytest.approx(
        sql.loc["Jan-2027", "expected_net_commission_gbp"], rel=1e-6
    )
    assert kpis["Revenue at risk"].delta == pytest.approx(
        sql.loc["Jan-2027", "live_commission_loss_share"]
        - sql.loc["Jan-2026", "live_commission_loss_share"],
        abs=1e-9,
    )
    assert kpis["Cancellation rate"].value == pytest.approx(
        sql.loc["Sep-2026", "cancellation_rate"]
    )
    assert kpis["Lead conversion"].delta == pytest.approx(
        sql.loc["Sep-2026", "conversion_rate"] - sql.loc["Sep-2025", "conversion_rate"]
    )


def test_kpis_respect_filters(data):
    everywhere = {k.label: k.value for k in executive_kpis(data, Filters())}
    uk = {k.label: k.value for k in executive_kpis(data, Filters(countries=("UK",)))}
    assert 0 < uk["Booked commission"] < everywhere["Booked commission"]


def test_commission_by_intake_splits_open_and_closed(data):
    df = commission_by_intake(data, Filters()).set_index("intake")
    jan = df.loc["Jan-2027"]
    open_commission = data.bookings.loc[data.bookings["is_open"], "commission_gbp"].sum()
    assert jan["landed_or_expected_gbp"] + jan["lost_or_at_risk_gbp"] == pytest.approx(
        open_commission
    )


def test_headline_insights_come_from_named_queries(con):
    insights = headline_insights(lambda name: run_query(con, name))
    assert len(insights) == 3
    assert all(i.sql_file[:2].isdigit() for i in insights)
    assert "revenue at risk" in insights[0].headline


def test_simulator_neutral_settings_change_nothing(data):
    stats = pipeline_stats(data, Filters())
    inputs = WhatIfInputs(0, 0, 0, stats.current_sla_share)
    r = simulate(open_bookings(data, Filters()), stats, inputs)
    assert r.projected_enc_gbp == pytest.approx(r.base_enc_gbp)
    assert r.base_enc_gbp == pytest.approx(expected_net_commission_gbp(data), rel=1e-9)


def test_simulator_queue_lever_equals_saveable_revenue_metric(data):
    ops = data.assumptions["operations"]
    stats = pipeline_stats(data, Filters())
    inputs = WhatIfInputs(
        ops["queue_top_share"], ops["intervention_save_rate"], 0, stats.current_sla_share
    )
    r = simulate(open_bookings(data, Filters()), stats, inputs)
    assert r.calls_gain_gbp == pytest.approx(saveable_revenue_gbp(data), rel=1e-9)


def test_simulator_levers_are_monotonic(data):
    stats = pipeline_stats(data, Filters())
    bookings = open_bookings(data, Filters())
    low = simulate(bookings, stats, WhatIfInputs(0.1, 0.2, 0.2, stats.current_sla_share))
    high = simulate(bookings, stats, WhatIfInputs(0.4, 0.4, 0.8, 1.0))
    assert high.deposit_gain_gbp > low.deposit_gain_gbp > 0
    assert high.calls_gain_gbp > low.calls_gain_gbp > 0
    assert high.sla_gain_gbp > low.sla_gain_gbp == 0
