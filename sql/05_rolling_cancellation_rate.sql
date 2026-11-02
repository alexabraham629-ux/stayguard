-- name: 05_rolling_cancellation_rate
-- business_question: Is our cancellation rate trending up week over week, city by city?
-- stakeholder: Revenue / Finance Lead
-- techniques: CTE, city x week spine (CROSS JOIN + generate_series), date_trunc, named WINDOW with explicit frame ROWS BETWEEN 3 PRECEDING AND CURRENT ROW, AVG OVER vs SUM/SUM OVER
-- grain: one row per city per week (booking-week cohorts, closed intakes)
-- validated_by: tests/test_sql.py::test_rolling_cancellation_matches_metrics
--
-- Two rolling measures, on purpose:
--   rolling_4wk_avg_rate_pct    = average of the 4 weekly rates (what "rolling average" usually means)
--   rolling_4wk_pooled_rate_pct = cancellations / bookings over the 4 weeks
-- The pooled rate weights each booking equally; the simple average lets a 2-booking week swing the
-- trend as much as a 200-booking week. Use the pooled rate for decisions.

WITH cohort_bookings AS (
    SELECT
        city,
        CAST(date_trunc('week', booked_at) AS DATE) AS week_start,
        is_cancelled
    FROM v_bookings_gbp
    WHERE is_closed_intake           -- open-intake outcomes are not final yet
),
bounds AS (
    SELECT MIN(week_start) AS first_week, MAX(week_start) AS last_week
    FROM cohort_bookings
),
weeks AS (
    SELECT UNNEST(generate_series(first_week, last_week, INTERVAL 7 DAY)) AS week_ts
    FROM bounds
),
spine AS (
    -- Every city has a row for every week, so "3 PRECEDING" always means three calendar weeks.
    SELECT c.city, CAST(w.week_ts AS DATE) AS week_start
    FROM dim_city AS c
    CROSS JOIN weeks AS w
),
weekly AS (
    SELECT
        s.city,
        s.week_start,
        COUNT(b.week_start)                              AS bookings,
        COUNT(b.week_start) FILTER (WHERE b.is_cancelled) AS cancellations
    FROM spine AS s
    LEFT JOIN cohort_bookings AS b
           ON b.city = s.city
          AND b.week_start = s.week_start
    GROUP BY s.city, s.week_start
)
SELECT
    city,
    week_start,
    bookings,
    cancellations,
    ROUND(100.0 * cancellations / NULLIF(bookings, 0), 2)                    AS weekly_rate_pct,
    -- AVG skips weeks with no bookings (their rate is NULL).
    ROUND(100.0 * AVG(cancellations / NULLIF(bookings, 0)) OVER rolling_4wk, 2) AS rolling_4wk_avg_rate_pct,
    ROUND(100.0 * SUM(cancellations) OVER rolling_4wk
          / NULLIF(SUM(bookings) OVER rolling_4wk, 0), 2)                    AS rolling_4wk_pooled_rate_pct,
    SUM(bookings) OVER rolling_4wk                                           AS rolling_4wk_bookings
FROM weekly
WINDOW rolling_4wk AS (
    PARTITION BY city
    ORDER BY week_start
    ROWS BETWEEN 3 PRECEDING AND CURRENT ROW
)
ORDER BY city, week_start;
