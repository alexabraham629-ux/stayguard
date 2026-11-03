-- name: 16_budget_band_vs_conversion
-- business_question: Does a student's budget (price band) change how often they book, and how often they cancel once booked?
-- stakeholder: City / Supply Manager
-- techniques: inline VALUES band table joined with a range condition, two aggregations joined on band, AVG of booleans
-- grain: one row per weekly-budget band (closed intakes)
-- validated_by: tests/test_sql.py::test_budget_bands_reconcile

WITH bands AS (
    SELECT band_order, band_label, min_gbp, max_gbp
    FROM (VALUES
        (1, 'Under £150',  0,   150),
        (2, '£150–199',  150,   200),
        (3, '£200–249',  200,   250),
        (4, '£250–299',  250,   300),
        (5, '£300+',     300, 100000)
    ) AS t (band_order, band_label, min_gbp, max_gbp)
),
leads AS (
    SELECT s.budget_weekly_gbp, l.status = 'booked' AS booked
    FROM fact_lead AS l
    JOIN dim_intake AS i ON i.intake = l.intake
    JOIN dim_student AS s ON s.student_id = l.student_id
    WHERE i.is_closed
),
lead_bands AS (
    SELECT b.band_order, COUNT(*) AS leads, COUNT(*) FILTER (WHERE l.booked) AS booked_leads
    FROM leads AS l
    JOIN bands AS b ON l.budget_weekly_gbp >= b.min_gbp AND l.budget_weekly_gbp < b.max_gbp
    GROUP BY b.band_order
),
booking_bands AS (
    SELECT
        b.band_order,
        COUNT(*)                                          AS bookings,
        AVG(v.weekly_rent_gbp / s.budget_weekly_gbp)      AS avg_rent_to_budget,
        AVG(v.is_cancelled::INT)                          AS cancellation_rate
    FROM v_bookings_gbp AS v
    JOIN dim_student AS s ON s.student_id = v.student_id
    JOIN bands AS b ON s.budget_weekly_gbp >= b.min_gbp AND s.budget_weekly_gbp < b.max_gbp
    WHERE v.is_closed_intake
    GROUP BY b.band_order
)
SELECT
    b.band_order,
    b.band_label,
    lb.leads,
    lb.booked_leads,
    ROUND(100.0 * lb.booked_leads / lb.leads, 1)   AS conversion_pct,
    bb.bookings,
    ROUND(bb.avg_rent_to_budget, 3)                AS avg_rent_to_budget,
    ROUND(100.0 * bb.cancellation_rate, 1)         AS cancellation_pct
FROM bands AS b
JOIN lead_bands AS lb ON lb.band_order = b.band_order
LEFT JOIN booking_bands AS bb ON bb.band_order = b.band_order
ORDER BY b.band_order;
