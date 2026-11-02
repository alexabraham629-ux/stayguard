-- Baseline cancellation scores for open bookings (ADR-017). Phase 4's ML model replaces this
-- table; the baseline stays as the benchmark the model must beat.
--
-- Survival-aware (ADR-005): every open booking has already survived to the snapshot, which is
-- `days_left` days before its move-in. So we learn from closed-intake bookings that were still
-- alive at the same point before THEIR move-in, and ask how many cancelled after that point.

CREATE OR REPLACE TABLE scored_bookings AS
WITH horizon AS (
    SELECT
        m.snapshot_date,
        -- days from snapshot to the open intake (DATE - DATE is BIGINT; DATE - INTEGER is a DATE)
        CAST(MIN(i.intake_start_date) - m.snapshot_date AS INTEGER) AS days_left
    FROM meta_build AS m
    CROSS JOIN dim_intake AS i
    WHERE NOT i.is_closed
    GROUP BY m.snapshot_date
),
segmented AS (
    SELECT
        b.booking_id,
        b.is_closed_intake,
        b.is_open,
        b.booked_at,
        b.is_cancelled,
        b.cancelled_at,
        b.intake_start_date - h.days_left              AS as_of_date,   -- equivalent "today"
        b.visa_status_at_booking,
        b.deposit_paid,
        CASE
            WHEN b.days_booked_before_intake < 90  THEN 'under_90d'
            WHEN b.days_booked_before_intake < 180 THEN '90_179d'
            ELSE '180d_plus'
        END                                            AS lead_time_band
    FROM v_bookings_gbp AS b
    CROSS JOIN horizon AS h
),
history AS (   -- closed-intake bookings alive at their equivalent snapshot
    SELECT
        visa_status_at_booking,
        deposit_paid,
        lead_time_band,
        COALESCE(is_cancelled AND cancelled_at >= as_of_date, FALSE) AS cancelled_after_as_of
    FROM segmented
    WHERE is_closed_intake
      AND booked_at < as_of_date
      AND NOT COALESCE(is_cancelled AND cancelled_at < as_of_date, FALSE)
),
segment_rates AS (
    SELECT
        visa_status_at_booking,
        deposit_paid,
        lead_time_band,
        COUNT(*)                            AS n_history,
        AVG(cancelled_after_as_of::INT)     AS segment_rate
    FROM history
    GROUP BY ALL
),
overall AS (
    SELECT AVG(cancelled_after_as_of::INT) AS overall_rate FROM history
)
SELECT
    s.booking_id,
    -- Thin segments (< 50 historical bookings) fall back to the overall rate.
    CASE WHEN r.n_history >= 50 THEN r.segment_rate ELSE o.overall_rate END AS p_cancel,
    'baseline_segment_rate_v1'                                              AS model_version,
    h.snapshot_date                                                         AS scored_as_of
FROM segmented AS s
LEFT JOIN segment_rates AS r
       ON r.visa_status_at_booking = s.visa_status_at_booking
      AND r.deposit_paid = s.deposit_paid
      AND r.lead_time_band = s.lead_time_band
CROSS JOIN overall AS o
CROSS JOIN horizon AS h
WHERE s.is_open;
