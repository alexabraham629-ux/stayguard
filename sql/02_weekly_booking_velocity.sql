-- name: 02_weekly_booking_velocity
-- business_question: Are bookings coming in faster or slower than last week, and than the same week last year?
-- stakeholder: Revenue / Finance Lead
-- techniques: date spine with generate_series + UNNEST, date_trunc, LAG(1) for week-over-week, LAG(52) for same week last year
-- grain: one row per calendar week (Monday start)
-- validated_by: tests/test_sql.py::test_weekly_velocity_totals_and_lag

WITH bounds AS (
    SELECT
        date_trunc('week', MIN(booked_at)) AS first_week,
        date_trunc('week', MAX(booked_at)) AS last_week
    FROM v_bookings_gbp
),
week_spine AS (
    -- Every week exists, even with zero bookings, so LAG(1) is "last week" and LAG(52) is
    -- "same week last year". Without the spine, LAG would skip over empty weeks.
    SELECT UNNEST(generate_series(first_week, last_week, INTERVAL 7 DAY)) AS week_ts
    FROM bounds
),
weekly AS (
    SELECT
        CAST(date_trunc('week', booked_at) AS DATE) AS week_start,
        COUNT(*)                                    AS bookings,
        SUM(commission_gbp)                         AS booked_commission_gbp
    FROM v_bookings_gbp
    GROUP BY 1
),
filled AS (
    SELECT
        CAST(s.week_ts AS DATE)                 AS week_start,
        COALESCE(w.bookings, 0)                 AS bookings,
        COALESCE(w.booked_commission_gbp, 0)    AS booked_commission_gbp
    FROM week_spine AS s
    LEFT JOIN weekly AS w ON w.week_start = CAST(s.week_ts AS DATE)
),
with_lags AS (
    SELECT
        week_start,
        bookings,
        booked_commission_gbp,
        LAG(bookings, 1)  OVER (ORDER BY week_start) AS prev_week_bookings,
        LAG(bookings, 52) OVER (ORDER BY week_start) AS same_week_last_year_bookings
    FROM filled
)
SELECT
    week_start,
    bookings,
    ROUND(booked_commission_gbp, 2)                                    AS booked_commission_gbp,
    prev_week_bookings,
    bookings - prev_week_bookings                                      AS wow_change,
    ROUND(100.0 * (bookings - prev_week_bookings) / NULLIF(prev_week_bookings, 0), 1) AS wow_change_pct,
    same_week_last_year_bookings,
    ROUND(100.0 * (bookings - same_week_last_year_bookings)
          / NULLIF(same_week_last_year_bookings, 0), 1)                AS yoy_change_pct
FROM with_lags
ORDER BY week_start;
