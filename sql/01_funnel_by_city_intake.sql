-- name: 01_funnel_by_city_intake
-- business_question: Where do we lose students between enquiry and move-in, by city and intake?
-- stakeholder: City / Supply Manager
-- techniques: CTEs, conditional aggregation (COUNT FILTER), LEFT JOIN, NULLIF-safe ratios
-- grain: one row per city per intake
-- validated_by: tests/test_sql.py::test_funnel_matches_metrics

WITH lead_stages AS (
    -- The stage a lead reached comes from its stage timestamps (ADR-014), not just its final status.
    SELECT
        l.lead_id,
        l.intake,
        c.country,
        c.city,
        l.contacted_at IS NOT NULL   AS reached_contacted,
        l.shortlisted_at IS NOT NULL AS reached_shortlisted,
        l.status = 'booked'          AS reached_booked
    FROM fact_lead AS l
    JOIN dim_city AS c ON c.city_id = l.city_id
),
moved_in AS (
    -- Clean bookings only, so a duplicate booking row cannot double-count a move-in.
    SELECT lead_id
    FROM v_clean_bookings
    WHERE status = 'moved_in'
),
stage_counts AS (
    SELECT
        s.country,
        s.city,
        s.intake,
        COUNT(*)                                     AS leads,
        COUNT(*) FILTER (WHERE s.reached_contacted)   AS contacted,
        COUNT(*) FILTER (WHERE s.reached_shortlisted) AS shortlisted,
        COUNT(*) FILTER (WHERE s.reached_booked)      AS booked,
        COUNT(m.lead_id)                             AS moved_in
    FROM lead_stages AS s
    LEFT JOIN moved_in AS m ON m.lead_id = s.lead_id
    GROUP BY s.country, s.city, s.intake
)
SELECT
    sc.country,
    sc.city,
    sc.intake,
    i.is_closed                                               AS is_closed_intake,
    sc.leads,
    sc.contacted,
    sc.shortlisted,
    sc.booked,
    sc.moved_in,
    ROUND(100.0 * sc.contacted   / NULLIF(sc.leads, 0), 1)       AS pct_contacted,
    ROUND(100.0 * sc.shortlisted / NULLIF(sc.contacted, 0), 1)   AS pct_shortlisted_of_contacted,
    ROUND(100.0 * sc.booked      / NULLIF(sc.shortlisted, 0), 1) AS pct_booked_of_shortlisted,
    -- Move-in only makes sense once the intake has started.
    CASE WHEN i.is_closed THEN ROUND(100.0 * sc.moved_in / NULLIF(sc.booked, 0), 1) END
                                                              AS pct_moved_in_of_booked,
    ROUND(100.0 * sc.booked / NULLIF(sc.leads, 0), 1)         AS pct_lead_to_booking
FROM stage_counts AS sc
JOIN dim_intake AS i ON i.intake = sc.intake
ORDER BY i.sort_order, sc.country, sc.city;
