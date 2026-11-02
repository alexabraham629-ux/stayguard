-- name: 12_channel_unit_economics
-- business_question: Which acquisition channels bring students who book, stay booked and earn commission?
-- stakeholder: Revenue Lead / Marketing
-- techniques: two aggregations joined on a shared key, AVG of booleans, COUNT/SUM FILTER, value per lead, RANK()
-- grain: one row per lead channel (closed intakes)
-- validated_by: tests/test_sql.py::test_channel_economics_matches_metrics

WITH lead_funnel AS (
    SELECT
        l.channel,
        COUNT(*)                                  AS leads,
        COUNT(*) FILTER (WHERE l.status = 'booked') AS booked_leads
    FROM fact_lead AS l
    JOIN dim_intake AS i ON i.intake = l.intake
    WHERE i.is_closed
    GROUP BY l.channel
),
booking_value AS (
    SELECT
        channel,
        COUNT(*)                                        AS bookings,
        AVG(commission_gbp)                             AS avg_booked_commission_gbp,
        AVG(is_cancelled::INT)                          AS cancellation_rate,
        SUM(commission_gbp) FILTER (WHERE is_moved_in)  AS realised_commission_gbp
    FROM v_bookings_gbp
    WHERE is_closed_intake
    GROUP BY channel
)
SELECT
    f.channel,
    f.leads,
    f.booked_leads,
    ROUND(100.0 * f.booked_leads / f.leads, 1)                                AS conversion_pct,
    ROUND(v.avg_booked_commission_gbp, 2)                                     AS avg_booked_commission_gbp,
    ROUND(100.0 * v.cancellation_rate, 1)                                     AS cancellation_pct,
    ROUND(v.realised_commission_gbp, 2)                                       AS realised_commission_gbp,
    -- What one lead from this channel is worth after conversion AND cancellation.
    ROUND(v.realised_commission_gbp / f.leads, 2)                             AS realised_commission_per_lead_gbp,
    RANK() OVER (ORDER BY v.realised_commission_gbp / f.leads DESC)           AS value_rank
FROM lead_funnel AS f
JOIN booking_value AS v ON v.channel = f.channel
ORDER BY value_rank;
