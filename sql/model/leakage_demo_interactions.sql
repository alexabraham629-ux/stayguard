-- DELIBERATELY LEAKY. Used only by stayguard.model.pipeline.leakage_demonstration to show what
-- leakage looks like; never a model feature (these column names are in LEAKY_COLUMNS).
--
-- Counts every post-booking touch, including those AFTER the as-of point. For closed intakes those
-- later touches reveal the outcome: students who are about to cancel stop replying, and the touch
-- history of a cancelled booking ends at the cancellation (ADR-016).

SELECT
    booking_id,
    COUNT(*)                                              AS touches_all_time,
    AVG((outcome IN ('connected', 'replied'))::INT)       AS positive_touch_rate_all_time
FROM fact_interaction
WHERE booking_id IS NOT NULL
GROUP BY booking_id;
