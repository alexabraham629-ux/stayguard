-- name: 15_commission_by_intake
-- business_question: How much commission did each intake book, land and lose, and how is the open intake tracking against the last comparable intake at the same point in its cycle?
-- stakeholder: Revenue / Finance Lead
-- techniques: horizon CTE, conditional aggregation (SUM/COUNT FILTER), like-for-like "same point" flag, LAG() OVER (PARTITION BY intake_month ORDER BY sort_order) to find the comparable intake
-- grain: one row per intake
-- validated_by: tests/test_sql.py::test_commission_by_intake_matches_metrics
--
-- "Same point": a booking made at least `days_left` days before its move-in, i.e. by the
-- equivalent of today's date in that intake's cycle. Jan-2027 compares with Jan-2026, and so on.

WITH horizon AS (
    SELECT COALESCE(CAST(MIN(i.intake_start_date) - MAX(m.snapshot_date) AS INTEGER), 0) AS days_left
    FROM dim_intake AS i
    CROSS JOIN meta_build AS m
    WHERE NOT i.is_closed
),
bookings AS (
    SELECT
        b.intake,
        b.commission_gbp,
        b.is_moved_in,
        b.is_cancelled,
        b.is_open,
        b.days_booked_before_intake >= h.days_left AS booked_by_same_point,
        -- Still live at the same point (as-of) in the cycle: booked before it, not yet cancelled.
        b.booked_at < CAST(b.intake_start_date - h.days_left AS TIMESTAMP)
          AND NOT COALESCE(b.is_cancelled
                           AND b.cancelled_at < CAST(b.intake_start_date - h.days_left AS TIMESTAMP), FALSE)
                                                 AS live_at_same_point,
        s.p_cancel
    FROM v_bookings_gbp AS b
    CROSS JOIN horizon AS h
    LEFT JOIN scored_bookings AS s ON s.booking_id = b.booking_id
),
per_intake AS (
    SELECT
        intake,
        COUNT(*)                                                         AS bookings,
        SUM(commission_gbp)                                              AS booked_commission_gbp,
        COALESCE(SUM(commission_gbp) FILTER (WHERE is_moved_in), 0)      AS realised_commission_gbp,
        COALESCE(SUM(commission_gbp) FILTER (WHERE is_cancelled), 0)     AS lost_commission_gbp,
        SUM(commission_gbp * (1 - p_cancel)) FILTER (WHERE is_open)      AS expected_net_commission_gbp,
        SUM(commission_gbp * p_cancel) FILTER (WHERE is_open)            AS revenue_at_risk_gbp,
        COUNT(*) FILTER (WHERE booked_by_same_point)                     AS bookings_same_point,
        SUM(commission_gbp) FILTER (WHERE booked_by_same_point)          AS booked_commission_same_point_gbp,
        COALESCE(SUM(commission_gbp) FILTER (WHERE booked_by_same_point AND is_moved_in), 0)
                                                                         AS realised_commission_same_point_gbp,
        AVG(is_cancelled::INT)                                           AS cancellation_rate,
        -- Share of still-live commission lost after the same point (actual, closed intakes).
        SUM(commission_gbp) FILTER (WHERE live_at_same_point AND is_cancelled)
          / SUM(commission_gbp) FILTER (WHERE live_at_same_point)        AS actual_live_loss_share
    FROM bookings
    GROUP BY intake
),
lead_conversion AS (
    SELECT intake, AVG((status = 'booked')::INT) AS conversion_rate
    FROM fact_lead
    GROUP BY intake
),
joined AS (
    SELECT
        i.intake,
        i.intake_month,
        i.academic_year,
        i.is_closed,
        i.sort_order,
        p.bookings,
        p.booked_commission_gbp,
        p.realised_commission_gbp,
        p.lost_commission_gbp,
        p.expected_net_commission_gbp,
        p.revenue_at_risk_gbp,
        p.bookings_same_point,
        p.booked_commission_same_point_gbp,
        p.realised_commission_same_point_gbp,
        -- Outcome rates only once an intake has started.
        CASE WHEN i.is_closed THEN p.cancellation_rate END AS cancellation_rate,
        CASE WHEN i.is_closed THEN c.conversion_rate END   AS conversion_rate,
        -- Open intake: the model's expectation (Revenue at Risk / open commission).
        CASE WHEN i.is_closed THEN p.actual_live_loss_share
             ELSE p.revenue_at_risk_gbp / (p.expected_net_commission_gbp + p.revenue_at_risk_gbp)
        END                                                AS live_commission_loss_share
    FROM dim_intake AS i
    JOIN per_intake AS p ON p.intake = i.intake
    JOIN lead_conversion AS c ON c.intake = i.intake
)
SELECT
    intake,
    intake_month,
    academic_year,
    is_closed,
    bookings,
    ROUND(booked_commission_gbp, 2)                     AS booked_commission_gbp,
    ROUND(realised_commission_gbp, 2)                   AS realised_commission_gbp,
    ROUND(lost_commission_gbp, 2)                       AS lost_commission_gbp,
    ROUND(expected_net_commission_gbp, 2)               AS expected_net_commission_gbp,
    ROUND(revenue_at_risk_gbp, 2)                       AS revenue_at_risk_gbp,
    bookings_same_point,
    ROUND(booked_commission_same_point_gbp, 2)          AS booked_commission_same_point_gbp,
    ROUND(realised_commission_same_point_gbp, 2)        AS realised_commission_same_point_gbp,
    cancellation_rate,
    conversion_rate,
    live_commission_loss_share,
    LAG(intake) OVER comparable                         AS comparable_intake,
    ROUND(LAG(booked_commission_same_point_gbp) OVER comparable, 2)   AS comparable_booked_commission_same_point_gbp,
    ROUND(LAG(realised_commission_same_point_gbp) OVER comparable, 2) AS comparable_realised_commission_same_point_gbp
FROM joined
WINDOW comparable AS (PARTITION BY intake_month ORDER BY sort_order)
ORDER BY sort_order;
