-- name: 14_data_quality_report
-- business_question: Can we trust the data behind every StayGuard number? Which integrity rules fail, and are the known issues being caught?
-- stakeholder: Analytics team (and anyone about to quote a StayGuard number)
-- techniques: CTEs, UNION ALL of rule checks, anti-joins (LEFT JOIN ... IS NULL), COUNT(*) FILTER, window function via v_booking_duplicate_flags (LAG)
-- grain: one row per data-quality check
-- validated_by: tests/test_quality.py::test_planted_issues_detected_exactly
--
-- category = 'integrity' -> must be 0 failing rows
-- category = 'planted'   -> known issue deliberately present in the synthetic data; must be > 0 (detected)
-- category = 'info'      -> context, no pass/fail

WITH snapshot AS (
    SELECT snapshot_date + INTERVAL 1 DAY AS end_of_snapshot FROM meta_build
),
booking_city AS (
    SELECT b.booking_id, b.currency, c.currency AS city_currency
    FROM fact_booking AS b
    JOIN dim_property AS p ON p.property_id = b.property_id
    JOIN dim_city AS c ON c.city_id = p.city_id
),
checks AS (
    -- Planted issues -------------------------------------------------------------------------
    SELECT 'P1' AS check_id,
           'Duplicate booking rows (same student and property within 48h)' AS check_name,
           'planted' AS category, 'fact_booking' AS table_name,
           COUNT(*) FILTER (WHERE is_duplicate_row) AS failing_rows, COUNT(*) AS total_rows
    FROM v_booking_duplicate_flags
    UNION ALL
    SELECT 'P2', 'Contacted leads missing first_response_minutes', 'planted', 'fact_lead',
           COUNT(*) FILTER (WHERE first_response_minutes IS NULL), COUNT(*)
    FROM fact_lead WHERE contacted_at IS NOT NULL
    UNION ALL
    SELECT 'P3', 'Cancellation timestamped before its booking', 'planted', 'fact_cancellation',
           COUNT(*) FILTER (WHERE x.cancelled_at < b.booked_at), COUNT(*)
    FROM fact_cancellation AS x JOIN fact_booking AS b ON b.booking_id = x.booking_id
    UNION ALL
    SELECT 'P4', 'Bookings in non-GBP currency (convert with fx_to_gbp before summing)', 'planted', 'fact_booking',
           COUNT(*) FILTER (WHERE currency <> 'GBP'), COUNT(*)
    FROM fact_booking

    -- Integrity rules (must be zero) ---------------------------------------------------------
    UNION ALL
    SELECT 'I01', 'Duplicate primary keys', 'integrity', 'all tables',
           (SELECT COUNT(*) - COUNT(DISTINCT lead_id) FROM fact_lead)
         + (SELECT COUNT(*) - COUNT(DISTINCT booking_id) FROM fact_booking)
         + (SELECT COUNT(*) - COUNT(DISTINCT booking_id) FROM fact_cancellation)
         + (SELECT COUNT(*) - COUNT(DISTINCT interaction_id) FROM fact_interaction)
         + (SELECT COUNT(*) - COUNT(DISTINCT student_id) FROM dim_student)
         + (SELECT COUNT(*) - COUNT(DISTINCT property_id) FROM dim_property),
           (SELECT COUNT(*) FROM fact_lead) + (SELECT COUNT(*) FROM fact_booking)
         + (SELECT COUNT(*) FROM fact_cancellation) + (SELECT COUNT(*) FROM fact_interaction)
         + (SELECT COUNT(*) FROM dim_student) + (SELECT COUNT(*) FROM dim_property)
    UNION ALL
    SELECT 'I02', 'Leads whose student does not exist', 'integrity', 'fact_lead',
           COUNT(*) FILTER (WHERE s.student_id IS NULL), COUNT(*)
    FROM fact_lead AS l LEFT JOIN dim_student AS s ON s.student_id = l.student_id
    UNION ALL
    SELECT 'I03', 'Bookings whose lead or property does not exist', 'integrity', 'fact_booking',
           COUNT(*) FILTER (WHERE l.lead_id IS NULL OR p.property_id IS NULL), COUNT(*)
    FROM fact_booking AS b
    LEFT JOIN fact_lead AS l ON l.lead_id = b.lead_id
    LEFT JOIN dim_property AS p ON p.property_id = b.property_id
    UNION ALL
    SELECT 'I04', 'Cancellations whose booking does not exist', 'integrity', 'fact_cancellation',
           COUNT(*) FILTER (WHERE b.booking_id IS NULL), COUNT(*)
    FROM fact_cancellation AS x LEFT JOIN fact_booking AS b ON b.booking_id = x.booking_id
    UNION ALL
    SELECT 'I05', 'Interactions not linked to exactly one existing lead or booking', 'integrity', 'fact_interaction',
           COUNT(*) FILTER (WHERE (i.lead_id IS NULL) = (i.booking_id IS NULL)
                              OR (i.lead_id IS NOT NULL AND l.lead_id IS NULL)
                              OR (i.booking_id IS NOT NULL AND b.booking_id IS NULL)), COUNT(*)
    FROM fact_interaction AS i
    LEFT JOIN fact_lead AS l ON l.lead_id = i.lead_id
    LEFT JOIN fact_booking AS b ON b.booking_id = i.booking_id
    UNION ALL
    SELECT 'I06', 'Negative money amounts', 'integrity', 'fact_booking + fact_cancellation',
           (SELECT COUNT(*) FROM fact_booking
             WHERE weekly_rent_local < 0 OR gbv_local < 0 OR commission_local < 0)
         + (SELECT COUNT(*) FROM fact_cancellation WHERE refund_amount_local < 0),
           (SELECT COUNT(*) FROM fact_booking) + (SELECT COUNT(*) FROM fact_cancellation)
    UNION ALL
    SELECT 'I07', 'Commission does not equal GBV x commission rate (to the penny)', 'integrity', 'fact_booking',
           COUNT(*) FILTER (WHERE ABS(commission_local - ROUND(gbv_local * commission_rate, 2)) > 0.01), COUNT(*)
    FROM fact_booking
    UNION ALL
    SELECT 'I08', 'Refund larger than the booking value', 'integrity', 'fact_cancellation',
           COUNT(*) FILTER (WHERE x.refund_amount_local > b.gbv_local), COUNT(*)
    FROM fact_cancellation AS x JOIN fact_booking AS b ON b.booking_id = x.booking_id
    UNION ALL
    SELECT 'I09', 'Booking currency differs from its city currency', 'integrity', 'fact_booking',
           COUNT(*) FILTER (WHERE currency <> city_currency), COUNT(*)
    FROM booking_city
    UNION ALL
    SELECT 'I10', 'Booking currency with no FX rate', 'integrity', 'fact_booking',
           COUNT(*) FILTER (WHERE fx.currency IS NULL), COUNT(*)
    FROM fact_booking AS b
    LEFT JOIN (SELECT DISTINCT currency FROM dim_city) AS fx ON fx.currency = b.currency
    UNION ALL
    SELECT 'I11', 'Booking status and cancellation record disagree', 'integrity', 'fact_booking',
           COUNT(*) FILTER (WHERE (b.status = 'cancelled') <> (x.booking_id IS NOT NULL)), COUNT(*)
    FROM fact_booking AS b LEFT JOIN fact_cancellation AS x ON x.booking_id = b.booking_id
    UNION ALL
    SELECT 'I12', 'Cancellation on or after the move-in date', 'integrity', 'fact_cancellation',
           COUNT(*) FILTER (WHERE x.cancelled_at >= i.intake_start_date), COUNT(*)
    FROM fact_cancellation AS x
    JOIN fact_booking AS b ON b.booking_id = x.booking_id
    JOIN dim_intake AS i ON i.intake = b.intake
    UNION ALL
    SELECT 'I13', 'Events dated after the snapshot', 'integrity', 'all fact tables',
           (SELECT COUNT(*) FROM fact_lead, snapshot WHERE created_at >= end_of_snapshot)
         + (SELECT COUNT(*) FROM fact_booking, snapshot WHERE booked_at >= end_of_snapshot)
         + (SELECT COUNT(*) FROM fact_cancellation, snapshot WHERE cancelled_at >= end_of_snapshot)
         + (SELECT COUNT(*) FROM fact_interaction, snapshot WHERE ts >= end_of_snapshot),
           (SELECT COUNT(*) FROM fact_lead) + (SELECT COUNT(*) FROM fact_booking)
         + (SELECT COUNT(*) FROM fact_cancellation) + (SELECT COUNT(*) FROM fact_interaction)
    UNION ALL
    SELECT 'I14', 'Open bookings in an intake that has already started', 'integrity', 'fact_booking',
           COUNT(*) FILTER (WHERE b.status = 'open' AND i.is_closed), COUNT(*)
    FROM fact_booking AS b JOIN dim_intake AS i ON i.intake = b.intake
    UNION ALL
    SELECT 'I15', 'Bookings whose lead is not marked booked', 'integrity', 'fact_booking',
           COUNT(*) FILTER (WHERE l.status <> 'booked'), COUNT(*)
    FROM fact_booking AS b JOIN fact_lead AS l ON l.lead_id = b.lead_id

    -- Context ---------------------------------------------------------------------------------
    UNION ALL
    SELECT 'X01', 'Leads never contacted (no first response)', 'info', 'fact_lead',
           COUNT(*) FILTER (WHERE contacted_at IS NULL), COUNT(*)
    FROM fact_lead
    UNION ALL
    SELECT 'X02', 'Open bookings still to be resolved (Jan-2027)', 'info', 'fact_booking',
           COUNT(*) FILTER (WHERE status = 'open'), COUNT(*)
    FROM fact_booking
)
SELECT
    check_id,
    check_name,
    category,
    table_name,
    failing_rows,
    total_rows,
    ROUND(100.0 * failing_rows / NULLIF(total_rows, 0), 2) AS failing_pct
FROM checks
ORDER BY check_id;
