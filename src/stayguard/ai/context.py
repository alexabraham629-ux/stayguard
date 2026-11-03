"""Schema context for the NL-to-SQL prompts, built from the live database so it never drifts."""

from __future__ import annotations

import duckdb

from stayguard.metrics import METRICS

# Tables and views the AI may query (enforced in guardrails.py). fact_booking is allowed so the
# verifier can show what happens when duplicates are not removed; the prompt steers away from it.
ALLOWED_TABLES: tuple[str, ...] = (
    "v_bookings_gbp",
    "v_clean_bookings",
    "fact_booking",
    "fact_lead",
    "fact_cancellation",
    "fact_interaction",
    "dim_city",
    "dim_intake",
    "dim_agent",
    "dim_student",
    "dim_property",
    "dim_university",
    "scored_bookings",
    "meta_build",
    "meta_assumption",
)

TABLE_NOTES: dict[str, str] = {
    "v_bookings_gbp": "PREFERRED for bookings. One row per clean booking (duplicates removed), "
    "enriched with city, country, intake, student, channel and cancellation details. Money in GBP.",
    "v_clean_bookings": "Bookings with data-entry duplicates removed; money still in local "
    "currency.",
    "fact_booking": "Raw bookings INCLUDING ~0.5% data-entry duplicates; money in local currency.",
    "fact_lead": "One row per enquiry (lead), with funnel timestamps and final status.",
    "fact_cancellation": "One row per cancelled booking: when, why, refund (local currency).",
    "fact_interaction": "Calls / WhatsApp / emails on leads (lead_id) or bookings (booking_id).",
    "dim_city": "12 cities in UK, AU, IE with currency and fixed fx_to_gbp.",
    "dim_intake": "6 intakes; is_closed = move-in date on or before the 2026-10-31 snapshot.",
    "dim_agent": "Booking managers; max_daily_capacity = calls per day.",
    "dim_student": "Students: source country, UG/PG level, weekly budget (GBP).",
    "dim_property": "Properties: operator type, room type, rent (local), cancellation policy.",
    "dim_university": "Fictional universities.",
    "scored_bookings": "Model risk score p_cancel (0-1) for each OPEN booking (Jan-2027).",
    "meta_build": "snapshot_date: 'today' inside the data.",
    "meta_assumption": "Business assumptions (SLA minutes, save rate) as name/value rows.",
}

COLUMN_NOTES: dict[str, str] = {
    "is_closed_intake": "TRUE when the intake has moved in (outcomes final)",
    "is_open": "TRUE for open Jan-2027 bookings not (yet) cancelled",
    "is_cancelled": "TRUE when the booking was cancelled",
    "is_moved_in": "TRUE when the student moved in",
    "commission_gbp": "commission earned if the booking survives, GBP",
    "gbv_gbp": "weekly rent x tenancy weeks, GBP",
    "days_booked_before_intake": "lead time: days between booking and move-in",
    "visa_status_at_booking": "not_applied | pending | granted | not_required",
    "cancel_reason": "NULL unless cancelled; visa_refused, no_place, cooling_off, found_cheaper, "
    "duplicate_booking, changed_plans, other",
    "status": "lead: new|contacted|shortlisted|booked|lost; booking: open|cancelled|moved_in",
    "first_response_minutes": "minutes from enquiry to first contact; NULL if not contacted or "
    "missing",
    "p_cancel": "predicted probability the open booking cancels before move-in",
    "has_invalid_cancel_timestamp": "data issue: cancellation dated before booking",
}

EXAMPLES: tuple[tuple[str, str, str], ...] = (
    (
        "What was the cancellation rate for the Sep-2026 intake?",
        "SELECT AVG(is_cancelled::INT) AS cancellation_rate\n"
        "FROM v_bookings_gbp\nWHERE intake = 'Sep-2026'",
        "cancellation_rate | filters intakes=[Sep-2026] | group_by none",
    ),
    (
        "Cancellation rate by country for intakes that have moved in",
        "SELECT country, AVG(is_cancelled::INT) AS cancellation_rate, COUNT(*) AS bookings\n"
        "FROM v_bookings_gbp\nWHERE is_closed_intake\nGROUP BY country\nORDER BY country",
        "cancellation_rate | group_by country",
    ),
    (
        "How much commission do we expect to land from Jan-2027 bookings?",
        "SELECT SUM(b.commission_gbp * (1 - s.p_cancel)) AS expected_net_commission_gbp\n"
        "FROM v_bookings_gbp AS b\nJOIN scored_bookings AS s ON s.booking_id = b.booking_id\n"
        "WHERE b.is_open",
        "expected_net_commission | group_by none",
    ),
    (
        "Total gross booking value across all markets",
        "SELECT SUM(gbv_gbp) AS gbv_gbp FROM v_bookings_gbp",
        "gbv | group_by none  (never SUM(gbv_local): it mixes GBP, AUD and EUR)",
    ),
    (
        "Lead to booking conversion by channel",
        "SELECT l.channel, AVG((l.status = 'booked')::INT) AS conversion_rate, COUNT(*) AS leads\n"
        "FROM fact_lead AS l\nJOIN dim_intake AS i ON i.intake = l.intake\n"
        "WHERE i.is_closed\nGROUP BY l.channel\nORDER BY conversion_rate DESC",
        "lead_to_booking_conversion | group_by channel",
    ),
    (
        "What share of visa-pending bookings from Nigeria were cancelled because of a visa "
        "refusal?",
        "SELECT AVG(COALESCE(cancel_reason = 'visa_refused', FALSE)::INT) AS visa_refusal_rate,\n"
        "       COUNT(*) AS bookings\nFROM v_bookings_gbp\n"
        "WHERE is_closed_intake AND source_country = 'Nigeria'\n"
        "  AND visa_status_at_booking = 'pending'",
        "none (not a canonical metric) | COALESCE keeps non-cancelled bookings in the denominator",
    ),
    (
        "Top 5 cities by revenue at risk",
        "SELECT b.city, SUM(b.commission_gbp * s.p_cancel) AS revenue_at_risk_gbp\n"
        "FROM v_bookings_gbp AS b\nJOIN scored_bookings AS s ON s.booking_id = b.booking_id\n"
        "WHERE b.is_open\nGROUP BY b.city\nORDER BY revenue_at_risk_gbp DESC\nLIMIT 5",
        "revenue_at_risk | group_by city",
    ),
    (
        "Median first response time in minutes",
        "SELECT MEDIAN(first_response_minutes) AS median_first_response_minutes FROM fact_lead",
        "median_first_response | group_by none",
    ),
)

DUCKDB_NOTES = """- Booleans cast to numbers with ::INT; AVG(flag::INT) gives a rate.
- date_trunc('week', ts), date_diff('day', a, b), strftime(ts, '%Y-%m').
- MEDIAN(x), QUANTILE_CONT(x, 0.9); string equality is case-sensitive.
- Intakes are strings like 'Sep-2026', 'Jan-2027'; academic years like '2025-26'."""


def build_schema_context(con: duckdb.DuckDBPyConnection) -> str:
    """Markdown description of allowed tables, columns, metrics and worked examples."""
    cols = con.execute(
        """SELECT table_name, column_name, data_type
           FROM information_schema.columns
           ORDER BY table_name, ordinal_position"""
    ).fetchall()
    by_table: dict[str, list[str]] = {}
    for table, column, dtype in cols:
        if table in ALLOWED_TABLES:
            note = COLUMN_NOTES.get(column)
            by_table.setdefault(table, []).append(
                f"{column} {dtype}" + (f" -- {note}" if note else "")
            )
    lines = ["# Schema (DuckDB; only these tables/views may be queried)"]
    for table in ALLOWED_TABLES:
        if table in by_table:
            lines.append(f"\n## {table}\n{TABLE_NOTES[table]}")
            lines.extend(f"- {c}" for c in by_table[table])

    lines.append("\n# Canonical metrics (name: label [unit] - SQL reference)")
    lines.extend(f"- {m.name}: {m.label} [{m.unit}] - sql/{m.sql_file}" for m in METRICS.values())
    lines.append(
        "Definitions: cancellation_rate = cancelled / clean bookings, closed intakes; "
        "lead_to_booking_conversion = booked leads / leads, closed intakes; "
        "expected_net_commission = SUM(commission_gbp * (1 - p_cancel)) over open bookings; "
        "revenue_at_risk = SUM(commission_gbp * p_cancel) over open bookings; "
        "realised_commission = commission of moved-in bookings; gbv and booked_commission over all "
        "clean bookings; median_first_response = median minutes, NULLs excluded."
    )
    lines.append("\n# DuckDB notes\n" + DUCKDB_NOTES)
    lines.append("\n# Examples")
    for question, sql, note in EXAMPLES:
        lines.append(f"\nQ: {question}\n```sql\n{sql}\n```\ncanonical: {note}")
    return "\n".join(lines)
