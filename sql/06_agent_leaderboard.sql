-- name: 06_agent_leaderboard
-- business_question: Which booking managers convert best, respond fastest, keep cancellations low, and who is overloaded?
-- stakeholder: Ops Head / Booking-Manager Team Lead
-- techniques: CTEs per fact table, MEDIAN, COUNT FILTER, RANK(), NTILE(4) quartiles, LEFT JOINs onto the agent dimension
-- grain: one row per agent
-- validated_by: tests/test_sql.py::test_agent_leaderboard_matches_metrics

WITH lead_stats AS (
    SELECT
        l.agent_id,
        COUNT(*) FILTER (WHERE i.is_closed)                         AS closed_leads,
        COUNT(*) FILTER (WHERE i.is_closed AND l.status = 'booked') AS closed_booked,
        MEDIAN(l.first_response_minutes)                            AS median_first_response_minutes
    FROM fact_lead AS l
    JOIN dim_intake AS i ON i.intake = l.intake
    GROUP BY l.agent_id
),
booking_stats AS (
    SELECT
        agent_id,
        COUNT(*) FILTER (WHERE is_closed_intake)                    AS closed_bookings,
        COUNT(*) FILTER (WHERE is_closed_intake AND is_cancelled)   AS closed_cancellations,
        COUNT(*) FILTER (WHERE is_open)                             AS open_bookings
    FROM v_bookings_gbp
    GROUP BY agent_id
),
agent_kpis AS (
    SELECT
        a.agent_id,
        a.agent_name,
        a.team,
        a.max_daily_capacity,
        COALESCE(ls.closed_leads, 0)                                         AS closed_leads,
        ls.closed_booked / NULLIF(ls.closed_leads, 0)                        AS conversion_rate,
        ls.median_first_response_minutes,
        bs.closed_cancellations / NULLIF(bs.closed_bookings, 0)              AS cancellation_rate,
        COALESCE(bs.open_bookings, 0)                                        AS open_bookings,
        -- Agent Load = days of backlog: open bookings / calls the agent can make per day (ADR-007)
        COALESCE(bs.open_bookings, 0) / a.max_daily_capacity                 AS load_days
    FROM dim_agent AS a
    LEFT JOIN lead_stats AS ls ON ls.agent_id = a.agent_id
    LEFT JOIN booking_stats AS bs ON bs.agent_id = a.agent_id
)
SELECT
    agent_id,
    agent_name,
    team,
    closed_leads,
    ROUND(100.0 * conversion_rate, 1)                         AS conversion_pct,
    median_first_response_minutes,
    ROUND(100.0 * cancellation_rate, 1)                       AS cancellation_pct,
    open_bookings,
    max_daily_capacity,
    ROUND(load_days, 2)                                       AS load_days,
    RANK()   OVER (ORDER BY conversion_rate DESC)             AS conversion_rank,
    -- Quartile 1 is always the best quarter of the team.
    NTILE(4) OVER (ORDER BY conversion_rate DESC)             AS conversion_quartile,
    NTILE(4) OVER (ORDER BY median_first_response_minutes)    AS response_quartile,
    NTILE(4) OVER (ORDER BY cancellation_rate)                AS cancellation_quartile,
    RANK()   OVER (ORDER BY load_days DESC)                   AS load_rank,
    load_days > 1                                             AS over_capacity
FROM agent_kpis
ORDER BY conversion_rank, agent_id;
