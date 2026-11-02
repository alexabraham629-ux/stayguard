-- Shared views. Every analysis query builds on these instead of the raw fact tables.

-- Flags data-entry duplicates: a booking for the same student and property entered within
-- 48 hours of the previous one (ADR-008). Business cancellations with reason
-- 'duplicate_booking' are NOT flagged here; they are real bookings the student later dropped.
CREATE OR REPLACE VIEW v_booking_duplicate_flags AS
WITH ordered AS (
    SELECT
        booking_id,
        student_id,
        property_id,
        booked_at,
        LAG(booking_id) OVER w AS previous_booking_id,
        LAG(booked_at)  OVER w AS previous_booked_at
    FROM fact_booking
    WINDOW w AS (PARTITION BY student_id, property_id ORDER BY booked_at, booking_id)
)
SELECT
    booking_id,
    previous_booking_id,
    COALESCE(booked_at - previous_booked_at <= INTERVAL 48 HOUR, FALSE) AS is_duplicate_row,
    CASE WHEN booked_at - previous_booked_at <= INTERVAL 48 HOUR THEN previous_booking_id END AS duplicate_of
FROM ordered;

-- Bookings with data-entry duplicates removed (the earliest entry is kept).
CREATE OR REPLACE VIEW v_clean_bookings AS
SELECT
    b.booking_id,
    b.lead_id,
    b.student_id,
    b.property_id,
    b.agent_id,
    b.booked_at,
    b.intake,
    b.tenancy_weeks,
    b.weekly_rent_local,
    b.currency,
    b.gbv_local,
    b.commission_rate,
    b.commission_local,
    b.deposit_paid,
    b.visa_status_at_booking,
    b.days_booked_before_intake,
    b.status
FROM fact_booking AS b
JOIN v_booking_duplicate_flags AS d ON d.booking_id = b.booking_id
WHERE NOT d.is_duplicate_row;

-- Clean bookings enriched with context, with every money column converted to GBP.
-- Use the *_gbp columns for any total: summing *_local across countries mixes currencies.
CREATE OR REPLACE VIEW v_bookings_gbp AS
SELECT
    b.booking_id,
    b.lead_id,
    b.student_id,
    b.property_id,
    b.agent_id,
    b.booked_at,
    b.intake,
    i.academic_year,
    i.intake_start_date,
    i.is_closed                                    AS is_closed_intake,
    c.city_id,
    c.city,
    c.country,
    p.operator_type,
    p.room_type,
    p.has_no_visa_no_pay,
    p.cooling_off_days,
    s.source_country,
    s.level,
    s.has_guarantor,
    l.channel,
    b.tenancy_weeks,
    b.currency,
    c.fx_to_gbp,
    b.weekly_rent_local,
    b.weekly_rent_local * c.fx_to_gbp              AS weekly_rent_gbp,
    b.gbv_local,
    b.gbv_local * c.fx_to_gbp                      AS gbv_gbp,
    b.commission_rate,
    b.commission_local,
    b.commission_local * c.fx_to_gbp               AS commission_gbp,
    b.deposit_paid,
    b.visa_status_at_booking,
    b.days_booked_before_intake,
    b.status,
    b.status = 'cancelled'                         AS is_cancelled,
    b.status = 'moved_in'                          AS is_moved_in,
    b.status = 'open'                              AS is_open,
    x.cancelled_at,
    x.reason                                       AS cancel_reason,
    x.days_after_booking,
    x.refund_amount_local * c.fx_to_gbp            AS refund_gbp,
    -- Planted issue: a few cancellations are timestamped before the booking. Keep the
    -- cancellation in rates, but exclude these rows from any timing analysis.
    COALESCE(x.cancelled_at < b.booked_at, FALSE)  AS has_invalid_cancel_timestamp
FROM v_clean_bookings AS b
JOIN dim_intake AS i         ON i.intake = b.intake
JOIN dim_property AS p       ON p.property_id = b.property_id
JOIN dim_city AS c           ON c.city_id = p.city_id
JOIN dim_student AS s        ON s.student_id = b.student_id
JOIN fact_lead AS l          ON l.lead_id = b.lead_id
LEFT JOIN fact_cancellation AS x ON x.booking_id = b.booking_id;
