-- Model features for every booking, computed AS OF a point before its move-in (ADR-005).
--
-- as_of_date = move-in date - days_left, where days_left is how far today's snapshot is from the
-- open intake's move-in. For open bookings as_of_date is the snapshot itself; for closed intakes it
-- is the equivalent "today" in that past cycle.
--
-- LEAKAGE RULES (enforced by stayguard.model.features.assert_no_leakage and tests/test_model.py):
--   * booking attributes: only fields known when the booking was made
--   * interactions:       only touches strictly before as_of_date (ADR-016)
--   * outcome fields:     used ONLY to build the label, never as features

WITH horizon AS (
    SELECT
        m.snapshot_date,
        CAST(MIN(i.intake_start_date) - m.snapshot_date AS INTEGER) AS days_left
    FROM meta_build AS m
    CROSS JOIN dim_intake AS i
    WHERE NOT i.is_closed
    GROUP BY m.snapshot_date
),
base AS (
    SELECT
        b.booking_id,
        b.intake,
        b.agent_id,
        b.is_closed_intake,
        b.is_open,
        b.commission_gbp,
        b.booked_at,
        CAST(b.intake_start_date - h.days_left AS TIMESTAMP)  AS as_of_ts,
        b.is_cancelled,
        b.cancelled_at
    FROM v_bookings_gbp AS b
    CROSS JOIN horizon AS h
),
population AS (
    -- Alive at the as-of point: booked before it and not already cancelled by then.
    SELECT
        booking_id,
        intake,
        agent_id,
        is_closed_intake,
        is_open,
        commission_gbp,
        booked_at,
        as_of_ts,
        -- LABEL (closed intakes only): cancelled after the as-of point, before move-in.
        CASE WHEN is_closed_intake
             THEN COALESCE(is_cancelled AND cancelled_at >= as_of_ts, FALSE)::INT
        END AS target
    FROM base
    WHERE booked_at < as_of_ts
      AND NOT COALESCE(is_cancelled AND cancelled_at < as_of_ts, FALSE)
),
agent_counts AS (
    -- Each agent's live bookings at the as-of point, in days of backlog (ADR-007).
    SELECT
        p.intake,
        p.agent_id,
        a.team,
        COUNT(*) / a.max_daily_capacity AS load_days
    FROM population AS p
    JOIN dim_agent AS a ON a.agent_id = p.agent_id
    GROUP BY p.intake, p.agent_id, a.team, a.max_daily_capacity
),
agent_load AS (
    -- Relative to the team average for that intake: transfers across intakes of very different
    -- sizes (Sep vs Jan), where absolute backlog is not comparable.
    SELECT
        intake,
        agent_id,
        load_days / AVG(load_days) OVER (PARTITION BY intake, team) AS load_vs_team
    FROM agent_counts
),
touches_before AS (
    SELECT
        p.booking_id,
        COUNT(*)                                                   AS touches,
        AVG((x.outcome IN ('connected', 'replied'))::INT)          AS positive_rate
    FROM population AS p
    JOIN fact_interaction AS x
      ON x.booking_id = p.booking_id
     AND x.ts < p.as_of_ts                                         -- strictly before as-of
    GROUP BY p.booking_id
)
SELECT
    p.booking_id,
    p.intake,
    p.agent_id,
    p.is_closed_intake,
    p.is_open,
    p.commission_gbp,
    p.as_of_ts,
    p.target,
    -- categorical features
    b.source_country,
    b.visa_status_at_booking,
    b.level,
    b.channel,
    b.operator_type,
    b.room_type,
    b.country,
    i.intake_month,
    -- numeric features (known at booking time)
    b.days_booked_before_intake,
    b.deposit_paid::INT                                            AS deposit_paid,
    b.has_guarantor::INT                                           AS has_guarantor,
    b.has_no_visa_no_pay::INT                                      AS has_no_visa_no_pay,
    b.cooling_off_days,
    b.tenancy_weeks,
    b.weekly_rent_gbp,
    b.weekly_rent_gbp / s.budget_weekly_gbp                        AS rent_to_budget,
    pr.rating                                                      AS property_rating,
    pr.distance_km_to_university,
    l.first_response_minutes,
    -- numeric features (as of the scoring point)
    al.load_vs_team                                                AS agent_load_vs_team,
    COALESCE(t.touches, 0)                                         AS touches_before_as_of,
    t.positive_rate                                                AS positive_touch_rate_before_as_of
FROM population AS p
JOIN v_bookings_gbp AS b   ON b.booking_id = p.booking_id
JOIN dim_intake AS i       ON i.intake = p.intake
JOIN dim_student AS s      ON s.student_id = b.student_id
JOIN dim_property AS pr    ON pr.property_id = b.property_id
JOIN fact_lead AS l        ON l.lead_id = b.lead_id
JOIN agent_load AS al      ON al.intake = p.intake AND al.agent_id = p.agent_id
LEFT JOIN touches_before AS t ON t.booking_id = p.booking_id
ORDER BY p.booking_id;
