-- name: 13_action_queue
-- business_question: Which students should booking managers call today to save the most commission, within each agent's capacity?
-- stakeholder: Ops Head / Booking-Manager Team Lead
-- techniques: expected-loss ranking, ROW_NUMBER() globally and PARTITION BY agent, capacity check, concat_ws reason codes (NULL-skipping), team spare capacity via SUM() OVER (PARTITION BY team)
-- grain: one row per open booking, in call-priority order
-- validated_by: tests/test_sql.py::test_action_queue_respects_capacity

WITH settings AS (
    SELECT value AS save_rate FROM meta_assumption WHERE name = 'intervention_save_rate'
),
open_scored AS (
    SELECT
        b.booking_id,
        b.agent_id,
        a.agent_name,
        a.team,
        a.max_daily_capacity,
        b.country,
        b.city,
        b.source_country,
        b.intake,
        b.commission_gbp,
        s.p_cancel,
        b.commission_gbp * s.p_cancel AS expected_loss_gbp,
        b.visa_status_at_booking,
        b.deposit_paid,
        b.days_booked_before_intake,
        b.weekly_rent_gbp,
        st.budget_weekly_gbp
    FROM v_bookings_gbp AS b
    JOIN scored_bookings AS s ON s.booking_id = b.booking_id
    JOIN dim_agent AS a ON a.agent_id = b.agent_id
    JOIN dim_student AS st ON st.student_id = b.student_id
    WHERE b.is_open
),
with_reasons AS (
    SELECT
        *,
        -- Plain-English reason codes; concat_ws skips the NULLs from flags that do not apply.
        NULLIF(concat_ws(' + ',
            CASE visa_status_at_booking
                WHEN 'pending'     THEN 'visa pending'
                WHEN 'not_applied' THEN 'visa not applied'
            END,
            CASE WHEN NOT deposit_paid THEN 'no deposit' END,
            CASE WHEN days_booked_before_intake >= 180
                 THEN 'booked ' || CAST(ROUND(days_booked_before_intake / 30.4) AS INTEGER) || ' months early'
            END,
            CASE WHEN weekly_rent_gbp > budget_weekly_gbp * 1.10 THEN 'rent over budget' END
        ), '') AS reason_codes
    FROM open_scored
),
ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (ORDER BY expected_loss_gbp DESC, booking_id)                     AS priority_rank,
        ROW_NUMBER() OVER (PARTITION BY agent_id ORDER BY expected_loss_gbp DESC, booking_id) AS agent_queue_position
    FROM with_reasons
),
capacity AS (
    SELECT
        *,
        agent_queue_position <= max_daily_capacity AS call_today
    FROM ranked
),
team_slack AS (
    -- Calls left over today in each team, to absorb overloaded agents' overflow.
    SELECT team, SUM(max_daily_capacity - LEAST(open_bookings, max_daily_capacity)) AS team_spare_calls
    FROM (
        SELECT a.team, a.agent_id, a.max_daily_capacity, COUNT(c.booking_id) AS open_bookings
        FROM dim_agent AS a
        LEFT JOIN capacity AS c ON c.agent_id = a.agent_id
        GROUP BY a.team, a.agent_id, a.max_daily_capacity
    ) AS per_agent
    GROUP BY team
)
SELECT
    c.priority_rank,
    c.booking_id,
    c.agent_id,
    c.agent_name,
    c.team,
    c.agent_queue_position,
    c.max_daily_capacity,
    c.call_today,
    CASE
        WHEN c.call_today THEN 'Call today'
        ELSE 'Over capacity: reassign within ' || c.team || ' (' || t.team_spare_calls || ' spare calls today)'
    END                                                   AS assignment,
    c.country,
    c.city,
    c.source_country,
    c.intake,
    ROUND(c.commission_gbp, 2)                            AS commission_gbp,
    ROUND(c.p_cancel, 4)                                  AS p_cancel,
    ROUND(c.expected_loss_gbp, 2)                         AS expected_loss_gbp,
    ROUND(c.expected_loss_gbp * s.save_rate, 2)           AS saveable_if_called_gbp,
    COALESCE(c.reason_codes, 'no major risk flags')       AS reason_codes
FROM capacity AS c
JOIN team_slack AS t ON t.team = c.team
CROSS JOIN settings AS s
ORDER BY c.priority_rank;
