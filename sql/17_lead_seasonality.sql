-- name: 17_lead_seasonality
-- business_question: When in the year do students enquire for each intake, so we can staff and spend ahead of the peak?
-- stakeholder: Ops Head / Marketing
-- techniques: date_trunc('month'), date_diff to a reference date, strftime month labels, share of partition with SUM() OVER (PARTITION BY ...)
-- grain: one row per intake per enquiry month
-- validated_by: tests/test_sql.py::test_lead_seasonality_shares

WITH monthly AS (
    SELECT
        l.intake,
        i.intake_month,
        i.is_closed,
        i.sort_order,
        CAST(date_trunc('month', l.created_at) AS DATE)                           AS enquiry_month,
        date_diff('month', date_trunc('month', l.created_at), date_trunc('month', i.intake_start_date))
                                                                                 AS months_before_intake,
        COUNT(*)                                                                 AS leads
    FROM fact_lead AS l
    JOIN dim_intake AS i ON i.intake = l.intake
    GROUP BY l.intake, i.intake_month, i.is_closed, i.sort_order, enquiry_month, months_before_intake
)
SELECT
    intake,
    intake_month,
    is_closed            AS is_closed_intake,
    enquiry_month,
    strftime(enquiry_month, '%b')                                            AS month_label,
    months_before_intake,
    leads,
    ROUND(100.0 * leads / SUM(leads) OVER (PARTITION BY intake), 2)          AS share_of_intake_pct
FROM monthly
ORDER BY sort_order, enquiry_month;
