-- name: 09_source_country_visa_risk
-- business_question: Which source countries and visa situations cancel most, and how much is visa refusal?
-- stakeholder: Revenue Lead / City Manager
-- techniques: GROUP BY two dimensions, COUNT FILTER, COALESCE for NULL-safe flags, partition-level ratio with SUM() OVER (PARTITION BY ...)
-- grain: one row per source country per visa status at booking (closed intakes)
-- validated_by: tests/test_sql.py::test_visa_risk_matches_pandas

WITH cells AS (
    SELECT
        source_country,
        visa_status_at_booking,
        COUNT(*)                                                      AS bookings,
        COUNT(*) FILTER (WHERE is_cancelled)                          AS cancellations,
        -- cancel_reason is NULL for bookings that did not cancel; COUNT FILTER handles that safely.
        COUNT(*) FILTER (WHERE cancel_reason = 'visa_refused')        AS visa_refusals
    FROM v_bookings_gbp
    WHERE is_closed_intake
    GROUP BY source_country, visa_status_at_booking
)
SELECT
    source_country,
    visa_status_at_booking,
    bookings,
    cancellations,
    ROUND(100.0 * cancellations / bookings, 1)                         AS cancellation_pct,
    visa_refusals,
    ROUND(100.0 * visa_refusals / bookings, 1)                         AS visa_refusal_pct,
    -- How this cell compares with the same country's overall rate, in percentage points.
    ROUND(100.0 * (cancellations / bookings
          - SUM(cancellations) OVER (PARTITION BY source_country)
            / SUM(bookings) OVER (PARTITION BY source_country)), 1)    AS vs_country_avg_pp,
    bookings < 30                                                      AS small_sample
FROM cells
ORDER BY source_country, visa_status_at_booking;
