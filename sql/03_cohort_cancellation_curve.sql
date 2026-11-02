-- name: 03_cohort_cancellation_curve
-- business_question: How quickly after booking do cancellations happen, and is the newest intake cohort tracking worse?
-- stakeholder: Revenue / Finance Lead
-- techniques: inline VALUES bucket table, CROSS JOIN to build a complete grid, running total SUM() OVER (PARTITION BY ... ORDER BY ... ROWS UNBOUNDED PRECEDING)
-- grain: one row per intake cohort per days-since-booking bucket
-- validated_by: tests/test_sql.py::test_cohort_curve_ends_at_cancellation_rate

WITH buckets AS (
    SELECT bucket_order, bucket_label, min_day, max_day
    FROM (VALUES
        (1, '0-7 days',     0,   7),
        (2, '8-30 days',    8,  30),
        (3, '31-60 days',  31,  60),
        (4, '61-90 days',  61,  90),
        (5, '91-180 days', 91, 180),
        (6, '181+ days',  181, 100000)
    ) AS t (bucket_order, bucket_label, min_day, max_day)
),
cohorts AS (
    SELECT intake, COUNT(*) AS cohort_bookings
    FROM v_bookings_gbp
    GROUP BY intake
),
timed_cancellations AS (
    -- Rows with a cancellation timestamp before the booking (planted issue) have no valid timing.
    SELECT intake, days_after_booking
    FROM v_bookings_gbp
    WHERE is_cancelled AND NOT has_invalid_cancel_timestamp
),
excluded AS (
    SELECT intake, COUNT(*) AS excluded_invalid_timestamps
    FROM v_bookings_gbp
    WHERE has_invalid_cancel_timestamp
    GROUP BY intake
),
grid AS (
    SELECT
        c.intake,
        c.cohort_bookings,
        b.bucket_order,
        b.bucket_label,
        COUNT(t.intake) AS cancellations_in_bucket
    FROM cohorts AS c
    CROSS JOIN buckets AS b
    LEFT JOIN timed_cancellations AS t
           ON t.intake = c.intake
          AND t.days_after_booking BETWEEN b.min_day AND b.max_day
    GROUP BY c.intake, c.cohort_bookings, b.bucket_order, b.bucket_label
),
cumulative AS (
    SELECT
        intake,
        cohort_bookings,
        bucket_order,
        bucket_label,
        cancellations_in_bucket,
        SUM(cancellations_in_bucket) OVER (
            PARTITION BY intake
            ORDER BY bucket_order
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS cumulative_cancellations
    FROM grid
)
SELECT
    cu.intake,
    i.is_closed                                                          AS is_closed_intake,
    cu.bucket_order,
    cu.bucket_label,
    cu.cohort_bookings,
    cu.cancellations_in_bucket,
    cu.cumulative_cancellations,
    ROUND(100.0 * cu.cumulative_cancellations / cu.cohort_bookings, 2)   AS cumulative_cancellation_pct,
    COALESCE(e.excluded_invalid_timestamps, 0)                           AS excluded_invalid_timestamps
FROM cumulative AS cu
JOIN dim_intake AS i ON i.intake = cu.intake
LEFT JOIN excluded AS e ON e.intake = cu.intake
ORDER BY i.sort_order, cu.bucket_order;
