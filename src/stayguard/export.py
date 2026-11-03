"""`make export`: write a star schema for Power BI / Tableau as CSV and Parquet (data/exports/).

Two facts (bookings, leads) at their natural grain, with every money column already in GBP,
and conformed dimensions including a date table. The model in dashboards/powerbi_spec.md is
built on exactly these files.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from stayguard.config import DB_PATH, EXPORTS_DIR
from stayguard.db import connect

STAR_SCHEMA: dict[str, str] = {
    "fact_bookings": """
        SELECT
            b.booking_id, b.lead_id, b.student_id, b.property_id, b.agent_id, b.city_id,
            b.intake, b.channel,
            CAST(b.booked_at AS DATE)                     AS booked_date,
            CAST(b.cancelled_at AS DATE)                  AS cancelled_date,
            b.status, b.is_cancelled, b.is_moved_in, b.is_open,
            b.cancel_reason, b.has_invalid_cancel_timestamp,
            b.visa_status_at_booking, b.deposit_paid, b.days_booked_before_intake,
            b.tenancy_weeks, b.currency, b.fx_to_gbp,
            b.weekly_rent_gbp, b.gbv_gbp, b.commission_rate, b.commission_gbp,
            COALESCE(b.refund_gbp, 0)                     AS refund_gbp,
            s.p_cancel,
            CASE WHEN b.is_open THEN b.commission_gbp * (1 - s.p_cancel) END
                                                          AS expected_net_commission_gbp,
            CASE WHEN b.is_open THEN b.commission_gbp * s.p_cancel END
                                                          AS revenue_at_risk_gbp
        FROM v_bookings_gbp AS b
        LEFT JOIN scored_bookings AS s ON s.booking_id = b.booking_id
    """,
    "fact_leads": """
        SELECT
            l.lead_id, l.student_id, l.city_id, l.agent_id, l.intake, l.channel,
            CAST(l.created_at AS DATE)                    AS created_date,
            l.first_response_minutes,
            l.first_response_minutes > (SELECT value FROM meta_assumption
                                        WHERE name = 'late_first_response_minutes') AS breached_sla,
            l.contacted_at IS NOT NULL                    AS reached_contacted,
            l.shortlisted_at IS NOT NULL                  AS reached_shortlisted,
            l.status = 'booked'                           AS reached_booked,
            l.status, l.lost_reason
        FROM fact_lead AS l
    """,
    "dim_date": """
        WITH bounds AS (
            SELECT MIN(d) AS first_day, MAX(d) AS last_day FROM (
                SELECT CAST(created_at AS DATE) AS d FROM fact_lead
                UNION ALL SELECT intake_start_date FROM dim_intake
            )
        )
        SELECT
            CAST(day AS DATE)                             AS date,
            year(day)                                     AS year,
            month(day)                                    AS month,
            strftime(day, '%b')                           AS month_name,
            strftime(day, '%Y-%m')                        AS year_month,
            CAST(date_trunc('week', day) AS DATE)         AS week_start,
            weekofyear(day)                               AS iso_week
        FROM bounds, generate_series(first_day, last_day, INTERVAL 1 DAY) AS t(day)
    """,
    "dim_city": "SELECT city_id, city, country, currency, market_tier, fx_to_gbp FROM dim_city",
    "dim_intake": """SELECT intake, intake_start_date, intake_month, academic_year, is_closed,
                            sort_order
                     FROM dim_intake""",
    "dim_agent": """SELECT agent_id, agent_name, team, languages, hire_date, max_daily_capacity
                    FROM dim_agent""",
    "dim_student": """SELECT student_id, source_country, level, university_id, budget_weekly_gbp,
                             has_guarantor FROM dim_student""",
    "dim_property": """SELECT p.property_id, p.city_id, p.operator_type, p.room_type,
                              p.weekly_rent_local * c.fx_to_gbp AS weekly_rent_gbp,
                              p.has_no_visa_no_pay, p.cooling_off_days,
                              p.distance_km_to_university, p.rating
                       FROM dim_property p JOIN dim_city c ON c.city_id = p.city_id""",
    "dim_channel": "SELECT DISTINCT channel FROM fact_lead ORDER BY channel",
}


def export_star_schema(
    con: duckdb.DuckDBPyConnection, out_dir: Path = EXPORTS_DIR
) -> dict[str, int]:
    """Write every table as CSV and Parquet; returns row counts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, sql in STAR_SCHEMA.items():
        for fmt, ext in (("CSV, HEADER", "csv"), ("PARQUET", "parquet")):
            target = (out_dir / f"{name}.{ext}").as_posix()
            con.execute(f"COPY ({sql}) TO '{target}' (FORMAT {fmt})")
        counts[name] = con.execute(f"SELECT COUNT(*) FROM ({sql})").fetchone()[0]
    return counts


def main() -> None:
    with connect(DB_PATH) as con:
        counts = export_star_schema(con)
    for name, rows in counts.items():
        print(f"  {name:<16} {rows:>8,} rows -> data/exports/{name}.csv / .parquet")


if __name__ == "__main__":
    main()
