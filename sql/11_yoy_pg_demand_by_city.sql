-- name: 11_yoy_pg_demand_by_city
-- business_question: Is postgraduate demand softening, and where? (evidence for the 2025-26 market slowdown)
-- stakeholder: City / Supply Manager / Strategy
-- techniques: like-for-like filter from a derived horizon, city x year grid (CROSS JOIN) so LAG never skips a year, LAG() OVER (PARTITION BY city ORDER BY academic_year), CASE segments
-- grain: one row per city per academic year (PG bookings)
-- validated_by: tests/test_sql.py::test_yoy_pg_demand_matches_metrics
--
-- Like-for-like: the January intake of the current academic year is still open, so for EVERY
-- year we only count January-intake bookings made at least `days_left` days before move-in,
-- i.e. bookings made by the equivalent of today's date. September intakes are complete.

WITH horizon AS (
    SELECT COALESCE(CAST(MIN(i.intake_start_date) - MAX(m.snapshot_date) AS INTEGER), 0) AS days_left
    FROM dim_intake AS i
    CROSS JOIN meta_build AS m
    WHERE NOT i.is_closed
),
pg_bookings AS (
    SELECT b.country, b.city, b.academic_year
    FROM v_bookings_gbp AS b
    JOIN dim_intake AS i ON i.intake = b.intake
    CROSS JOIN horizon AS h
    WHERE b.level = 'PG'
      AND (i.intake_month = 'Sep' OR b.days_booked_before_intake >= h.days_left)
),
grid AS (
    SELECT c.country, c.city, y.academic_year
    FROM dim_city AS c
    CROSS JOIN (SELECT DISTINCT academic_year FROM dim_intake) AS y
),
counts AS (
    SELECT g.country, g.city, g.academic_year, COUNT(p.city) AS pg_bookings
    FROM grid AS g
    LEFT JOIN pg_bookings AS p
           ON p.city = g.city
          AND p.academic_year = g.academic_year
    GROUP BY g.country, g.city, g.academic_year
)
SELECT
    country,
    city,
    CASE
        WHEN city = 'London' THEN 'London'
        WHEN country = 'UK'  THEN 'UK non-London'
        ELSE 'AU/IE'
    END                                                                  AS segment,
    academic_year,
    pg_bookings,
    LAG(pg_bookings) OVER (PARTITION BY city ORDER BY academic_year)     AS prev_year_pg_bookings,
    ROUND(100.0 * (pg_bookings - LAG(pg_bookings) OVER (PARTITION BY city ORDER BY academic_year))
          / NULLIF(LAG(pg_bookings) OVER (PARTITION BY city ORDER BY academic_year), 0), 1)
                                                                         AS yoy_change_pct,
    'Jan intakes counted to the same point before move-in as today'      AS comparison_basis
FROM counts
ORDER BY country, city, academic_year;
