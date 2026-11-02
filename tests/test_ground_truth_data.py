"""The 8 planted effects (docs/DATA_GENERATION.md, "Ground truth") are visible in the raw data.

These check the generator. Phase 4 adds the stronger test: the model re-discovers them.
All cancellation comparisons use closed intakes from v_bookings_gbp.
"""

from tests.conftest import scalar

CLOSED = "FROM v_bookings_gbp WHERE is_closed_intake"


def cancel_rate(con, where: str) -> float:
    return scalar(con, f"SELECT AVG(is_cancelled::INT) {CLOSED} AND {where}")


def conversion(con, where: str) -> float:
    return scalar(
        con,
        f"""SELECT AVG((l.status = 'booked')::INT)
            FROM fact_lead l JOIN dim_intake i ON i.intake = l.intake
            WHERE i.is_closed AND {where}""",
    )


def visa_refusal_rate(con, country: str) -> float:
    return scalar(
        con,
        f"""SELECT AVG(COALESCE(cancel_reason = 'visa_refused', FALSE)::INT) {CLOSED}
            AND visa_status_at_booking <> 'not_required' AND source_country = '{country}'""",
    )


def test_e1_visa_status_and_country(con):
    unresolved = cancel_rate(con, "visa_status_at_booking IN ('pending', 'not_applied')")
    granted = cancel_rate(con, "visa_status_at_booking = 'granted'")
    assert unresolved > 1.4 * granted
    rates = {c: visa_refusal_rate(con, c) for c in ("Nigeria", "Pakistan", "India", "China", "USA")}
    assert (
        min(rates["Nigeria"], rates["Pakistan"])
        > rates["India"]
        > max(rates["China"], rates["USA"])
    )


def test_e2_no_deposit_cancels_more(con):
    assert cancel_rate(con, "NOT deposit_paid") > 1.2 * cancel_rate(con, "deposit_paid")


def test_e3_early_bookings_cancel_more(con):
    early = cancel_rate(con, "days_booked_before_intake >= 180")
    late = cancel_rate(con, "days_booked_before_intake < 30")
    middle = cancel_rate(con, "days_booked_before_intake BETWEEN 30 AND 179")
    assert early > middle > late
    shopping = "COALESCE(cancel_reason IN ('found_cheaper', 'duplicate_booking'), FALSE)::INT"
    assert scalar(
        con, f"SELECT AVG({shopping}) {CLOSED} AND days_booked_before_intake >= 180"
    ) > 2 * scalar(con, f"SELECT AVG({shopping}) {CLOSED} AND days_booked_before_intake < 30")


def test_e4_slow_first_response_converts_worse(con):
    assert conversion(con, "l.first_response_minutes > 240") < 0.75 * conversion(
        con, "l.first_response_minutes <= 240"
    )


def test_e5_channel_ranking(con):
    rates = {
        ch: conversion(con, f"l.channel = '{ch}'")
        for ch in (
            "organic",
            "paid_search",
            "referral",
            "ambassador",
            "partner_consultancy",
            "loan_partner",
        )
    }
    others = [r for ch, r in rates.items() if ch not in ("ambassador", "partner_consultancy")]
    assert min(rates["ambassador"], rates["partner_consultancy"]) > max(others)
    assert rates["paid_search"] == min(rates.values())


def test_e6_pg_demand_softens_outside_london(con):
    def pg_bookings(year: str, segment: str) -> int:
        return scalar(
            con,
            f"""SELECT COUNT(*) FROM v_bookings_gbp
                WHERE level = 'PG' AND academic_year = '{year}' AND {segment}""",
        )

    non_london = "country = 'UK' AND city <> 'London'"
    london = "city = 'London'"
    drop_non_london = pg_bookings("2025-26", non_london) / pg_bookings("2024-25", non_london)
    drop_london = pg_bookings("2025-26", london) / pg_bookings("2024-25", london)
    assert drop_non_london < 0.85
    assert drop_non_london < drop_london


def test_e7_overloaded_agents(con, generated):
    overloaded = generated.manifest["ground_truth"]["overloaded_agent_ids"]
    ids = ", ".join(map(str, overloaded))
    assert cancel_rate(con, f"agent_id IN ({ids})") > 1.1 * cancel_rate(
        con, f"agent_id NOT IN ({ids})"
    )
    top_loaded = con.execute(
        """SELECT b.agent_id
           FROM v_bookings_gbp b JOIN dim_agent a ON a.agent_id = b.agent_id
           WHERE b.is_open
           GROUP BY b.agent_id, a.max_daily_capacity
           ORDER BY COUNT(*) / a.max_daily_capacity DESC
           LIMIT 2"""
    ).fetchall()
    assert sorted(r[0] for r in top_loaded) == overloaded


def test_e8_lead_seasonality(con):
    def share(intake_month: str, months: str) -> float:
        return scalar(
            con,
            f"""SELECT AVG((month(l.created_at) IN ({months}))::INT)
                FROM fact_lead l JOIN dim_intake i ON i.intake = l.intake
                WHERE i.is_closed AND i.intake_month = '{intake_month}'""",
        )

    assert share("Sep", "2, 3, 4, 5, 6, 7") > 0.7
    assert share("Jan", "9, 10, 11") > 0.6
