-- name: 04_cancellation_reasons_pareto
-- business_question: Which few cancellation reasons cause most of our lost bookings and commission (the 80/20)?
-- stakeholder: Ops Head / Revenue Lead
-- techniques: aggregation, RANK(), running share with SUM() OVER (ORDER BY ... ROWS UNBOUNDED PRECEDING), grand total with SUM() OVER ()
-- grain: one row per cancellation reason (closed intakes)
-- validated_by: tests/test_sql.py::test_pareto_running_share

WITH reasons AS (
    SELECT
        cancel_reason,
        COUNT(*)             AS cancellations,
        SUM(commission_gbp)  AS lost_commission_gbp
    FROM v_bookings_gbp
    WHERE is_closed_intake AND is_cancelled
    GROUP BY cancel_reason
),
running AS (
    SELECT
        cancel_reason,
        cancellations,
        lost_commission_gbp,
        RANK() OVER (ORDER BY cancellations DESC) AS reason_rank,
        -- Tie-break on the reason name so the running total is deterministic.
        SUM(cancellations) OVER (
            ORDER BY cancellations DESC, cancel_reason
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )                                         AS running_cancellations,
        SUM(cancellations) OVER ()                AS total_cancellations
    FROM reasons
)
SELECT
    reason_rank,
    cancel_reason,
    cancellations,
    ROUND(lost_commission_gbp, 2)                                       AS lost_commission_gbp,
    ROUND(100.0 * cancellations / total_cancellations, 1)              AS share_pct,
    ROUND(100.0 * running_cancellations / total_cancellations, 1)      AS running_share_pct,
    -- "Vital few": reasons needed to reach 80% of cancellations (the share before this row is < 80%).
    (running_cancellations - cancellations) < 0.8 * total_cancellations AS in_vital_few
FROM running
ORDER BY reason_rank, cancel_reason;
