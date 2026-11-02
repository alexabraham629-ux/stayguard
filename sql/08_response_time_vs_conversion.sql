-- name: 08_response_time_vs_conversion
-- business_question: How much conversion do we lose when we are slow to answer a new lead?
-- stakeholder: Ops Head / Booking-Manager Team Lead
-- techniques: QUANTILE_CONT with a list of quantiles (one pass), list indexing, CASE bucketing, scalar subquery for the SLA threshold
-- grain: one row per response-time quintile (closed intakes, leads with a recorded response time)
-- validated_by: tests/test_sql.py::test_response_buckets_reconcile

WITH responded AS (
    -- Missing first_response_minutes (a planted data issue) are excluded and reported in sql/14.
    SELECT
        l.first_response_minutes AS minutes,
        l.status = 'booked'      AS booked
    FROM fact_lead AS l
    JOIN dim_intake AS i ON i.intake = l.intake
    WHERE i.is_closed
      AND l.first_response_minutes IS NOT NULL
),
cut_points AS (
    SELECT QUANTILE_CONT(minutes, [0.2, 0.4, 0.6, 0.8]) AS q
    FROM responded
),
sla AS (
    SELECT value AS sla_minutes FROM meta_assumption WHERE name = 'late_first_response_minutes'
),
bucketed AS (
    SELECT
        r.minutes,
        r.booked,
        CASE                                   -- DuckDB lists are 1-indexed
            WHEN r.minutes <= c.q[1] THEN 1
            WHEN r.minutes <= c.q[2] THEN 2
            WHEN r.minutes <= c.q[3] THEN 3
            WHEN r.minutes <= c.q[4] THEN 4
            ELSE 5
        END AS quintile
    FROM responded AS r
    CROSS JOIN cut_points AS c
)
SELECT
    b.quintile,
    MIN(b.minutes)                                                   AS min_minutes,
    MAX(b.minutes)                                                   AS max_minutes,
    COUNT(*)                                                         AS leads,
    COUNT(*) FILTER (WHERE b.booked)                                 AS booked,
    ROUND(100.0 * COUNT(*) FILTER (WHERE b.booked) / COUNT(*), 1)    AS conversion_pct,
    ROUND(100.0 * AVG((b.minutes > s.sla_minutes)::INT), 1)          AS pct_over_sla
FROM bucketed AS b
CROSS JOIN sla AS s
GROUP BY b.quintile
ORDER BY b.quintile;
