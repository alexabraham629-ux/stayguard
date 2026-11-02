-- name: 07_revenue_at_risk_by_city
-- business_question: How much of the open intake's booked commission will really land, and which cities carry the risk?
-- stakeholder: Revenue / Finance Lead
-- techniques: join to model scores, expected-value aggregation, share of total with SUM() OVER (), RANK()
-- grain: one row per city (open bookings only)
-- validated_by: tests/test_sql.py::test_revenue_at_risk_matches_metrics
--
-- ENC (Expected Net Commission) = SUM(commission x (1 - p_cancel))
-- Revenue at Risk               = SUM(commission x p_cancel)
-- p_cancel comes from scored_bookings (baseline in Phase 3, ML model from Phase 4).

WITH scored_open AS (
    SELECT
        b.country,
        b.city,
        b.commission_gbp,
        s.p_cancel,
        s.model_version
    FROM v_bookings_gbp AS b
    JOIN scored_bookings AS s ON s.booking_id = b.booking_id
    WHERE b.is_open
),
by_city AS (
    SELECT
        country,
        city,
        COUNT(*)                                AS open_bookings,
        SUM(commission_gbp)                     AS booked_commission_gbp,
        SUM(commission_gbp * (1 - p_cancel))    AS expected_net_commission_gbp,
        SUM(commission_gbp * p_cancel)          AS revenue_at_risk_gbp,
        AVG(p_cancel)                           AS avg_p_cancel,
        ANY_VALUE(model_version)                AS model_version
    FROM scored_open
    GROUP BY country, city
)
SELECT
    RANK() OVER (ORDER BY revenue_at_risk_gbp DESC)                          AS risk_rank,
    country,
    city,
    open_bookings,
    ROUND(booked_commission_gbp, 2)                                          AS booked_commission_gbp,
    ROUND(expected_net_commission_gbp, 2)                                    AS expected_net_commission_gbp,
    ROUND(revenue_at_risk_gbp, 2)                                            AS revenue_at_risk_gbp,
    ROUND(100.0 * revenue_at_risk_gbp / SUM(revenue_at_risk_gbp) OVER (), 1) AS share_of_total_risk_pct,
    ROUND(100.0 * avg_p_cancel, 1)                                           AS avg_p_cancel_pct,
    model_version
FROM by_city
ORDER BY risk_rank;
