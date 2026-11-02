-- name: 10_duplicate_booking_detection
-- business_question: Which booking rows are duplicates we must exclude, and which "duplicate" cancellations are real business events?
-- stakeholder: Analytics team / Ops Head
-- techniques: self-join with a time-window condition, ROW_NUMBER() to keep one match per row, EXTRACT(EPOCH FROM interval), UNION ALL of two labelled kinds
-- grain: one row per flagged booking
-- validated_by: tests/test_sql.py::test_duplicate_detection_matches_quality_report
--
-- Two different things (ADR-008):
--   data_entry_duplicate            : the same booking entered twice within 48h -> EXCLUDE (v_clean_bookings does)
--   business_duplicate_cancellation : a real booking the student cancelled because they booked elsewhere -> KEEP

WITH pairs AS (
    SELECT
        later.booking_id,
        earlier.booking_id                                                    AS original_booking_id,
        later.student_id,
        later.property_id,
        later.booked_at,
        ROUND(EXTRACT(EPOCH FROM later.booked_at - earlier.booked_at) / 3600.0, 1) AS hours_after_original,
        ROW_NUMBER() OVER (
            PARTITION BY later.booking_id
            ORDER BY earlier.booked_at, earlier.booking_id
        )                                                                     AS match_number
    FROM fact_booking AS later
    JOIN fact_booking AS earlier
      ON earlier.student_id = later.student_id
     AND earlier.property_id = later.property_id
     AND earlier.booking_id <> later.booking_id
     AND (earlier.booked_at < later.booked_at
          OR (earlier.booked_at = later.booked_at AND earlier.booking_id < later.booking_id))
     AND later.booked_at - earlier.booked_at <= INTERVAL 48 HOUR
),
data_entry AS (
    SELECT
        'data_entry_duplicate'                    AS duplicate_kind,
        booking_id,
        original_booking_id,
        student_id,
        property_id,
        booked_at,
        hours_after_original,
        'Exclude: same booking entered twice'     AS recommended_action
    FROM pairs
    WHERE match_number = 1        -- earliest matching original only
),
business AS (
    SELECT
        'business_duplicate_cancellation'         AS duplicate_kind,
        booking_id,
        CAST(NULL AS BIGINT)                      AS original_booking_id,
        student_id,
        property_id,
        booked_at,
        CAST(NULL AS DOUBLE)                      AS hours_after_original,
        'Keep: real booking, student booked elsewhere' AS recommended_action
    FROM v_bookings_gbp
    WHERE cancel_reason = 'duplicate_booking'
)
SELECT duplicate_kind, booking_id, original_booking_id, student_id, property_id, booked_at,
       hours_after_original, recommended_action
FROM data_entry
UNION ALL
SELECT duplicate_kind, booking_id, original_booking_id, student_id, property_id, booked_at,
       hours_after_original, recommended_action
FROM business
ORDER BY duplicate_kind DESC, booked_at, booking_id;
