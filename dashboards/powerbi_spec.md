# Power BI build spec — StayGuard

> Synthetic data, portfolio project. This spec lets you build the Power BI dashboard yourself in about
> two hours from the files that `make export` writes to `data/exports/`.

## 1. Get the data

1. Run `make data` and then `make export`.
2. In Power BI Desktop, choose **Get Data → Parquet** and load every `.parquet` file in `data/exports/`.
   - Prefer Parquet over CSV: it keeps the types (booleans, dates, decimals).
   - With CSV, set the `is_*`, `reached_*`, `deposit_paid` and `breached_sla` columns to **True/False**, and
     `*_date` to **Date**, in Power Query.
3. Mark `dim_date` as the date table: **Table tools → Mark as date table**, using `dim_date[date]`.

## 2. Star schema

| Table | Grain | Key columns | Notes |
|---|---|---|---|
| `fact_bookings` | One clean booking (duplicates removed) | `booking_id` | Money already in GBP. `p_cancel`, `expected_net_commission_gbp` and `revenue_at_risk_gbp` are filled only for open (Jan-2027) bookings |
| `fact_leads` | One lead (enquiry) | `lead_id` | Funnel flags (`reached_*`) and `breached_sla` (first response > 240 min) |
| `dim_date` | One day | `date` | Covers the first enquiry through the last move-in |
| `dim_intake` | One intake | `intake` | `is_closed` = moved in by the 2026-10-31 snapshot |
| `dim_city` | One city | `city_id` | `country`, `currency`, `fx_to_gbp` |
| `dim_agent` | One booking manager | `agent_id` | `max_daily_capacity` (calls per day) |
| `dim_student` | One student | `student_id` | `source_country`, `level` |
| `dim_property` | One property | `property_id` | Rent already in GBP |
| `dim_channel` | One acquisition channel | `channel` | |

### Relationships

All are many-to-one, single direction, from the fact to the dimension.

| From | To |
|---|---|
| `fact_bookings[booked_date]` | `dim_date[date]` |
| `fact_bookings[intake]` | `dim_intake[intake]` |
| `fact_bookings[city_id]` | `dim_city[city_id]` |
| `fact_bookings[agent_id]` | `dim_agent[agent_id]` |
| `fact_bookings[student_id]` | `dim_student[student_id]` |
| `fact_bookings[property_id]` | `dim_property[property_id]` |
| `fact_bookings[channel]` | `dim_channel[channel]` |
| `fact_leads[created_date]` | `dim_date[date]` |
| `fact_leads[intake]` | `dim_intake[intake]` |
| `fact_leads[city_id]` | `dim_city[city_id]` |
| `fact_leads[agent_id]` | `dim_agent[agent_id]` |
| `fact_leads[student_id]` | `dim_student[student_id]` |
| `fact_leads[channel]` | `dim_channel[channel]` |

Do **not** relate `dim_property` to `dim_city`: the facts already carry `city_id`, and a second path
would make the model ambiguous.

## 3. DAX measures

Create a measure table called `_Measures` (**Enter data**, with one empty column, which you then hide)
and add the measures below. Format money as **£#,0** and rates as **0.0%**.

```dax
Bookings = COUNTROWS ( fact_bookings )

Booked Commission = SUM ( fact_bookings[commission_gbp] )

Realised Commission =
CALCULATE ( [Booked Commission], fact_bookings[is_moved_in] = TRUE () )

Lost Commission =
CALCULATE ( [Booked Commission], fact_bookings[is_cancelled] = TRUE (), dim_intake[is_closed] = TRUE () )

-- Outcome rates use intakes that have moved in only (open outcomes are not final).
Cancellation Rate =
DIVIDE (
    CALCULATE ( [Bookings], fact_bookings[is_cancelled] = TRUE (), dim_intake[is_closed] = TRUE () ),
    CALCULATE ( [Bookings], dim_intake[is_closed] = TRUE () )
)

Survival Rate = 1 - [Cancellation Rate]

-- North star: open bookings only (the columns are blank for every other booking).
Expected Net Commission = SUM ( fact_bookings[expected_net_commission_gbp] )

Revenue at Risk = SUM ( fact_bookings[revenue_at_risk_gbp] )

Share of Open Commission at Risk =
DIVIDE ( [Revenue at Risk], [Expected Net Commission] + [Revenue at Risk] )

Leads = COUNTROWS ( fact_leads )

Lead to Booking Conversion =
DIVIDE (
    CALCULATE ( [Leads], fact_leads[reached_booked] = TRUE (), dim_intake[is_closed] = TRUE () ),
    CALCULATE ( [Leads], dim_intake[is_closed] = TRUE () )
)

-- MEDIAN skips blanks, so leads with no recorded response are excluded (as in metrics.py).
Median First Response (min) = MEDIAN ( fact_leads[first_response_minutes] )

SLA Breach Rate =
DIVIDE (
    CALCULATE ( [Leads], fact_leads[breached_sla] = TRUE () ),
    CALCULATE ( [Leads], NOT ISBLANK ( fact_leads[first_response_minutes] ) )
)

Booked Commission PY =
CALCULATE ( [Booked Commission], SAMEPERIODLASTYEAR ( dim_date[date] ) )

Booked Commission YoY % =
DIVIDE ( [Booked Commission] - [Booked Commission PY], [Booked Commission PY] )

-- Pooled (cancelled / booked over the window), like sql/05's recommended column.
Cancellation Rate (rolling 4 weeks) =
VAR LastDay = MAX ( dim_date[date] )
RETURN
    CALCULATE ( [Cancellation Rate], DATESINPERIOD ( dim_date[date], LastDay, -28, DAY ) )

-- Days of backlog (ADR-007): open bookings / daily call capacity.
Agent Load (days) =
DIVIDE (
    CALCULATE ( [Bookings], fact_bookings[is_open] = TRUE () ),
    SUM ( dim_agent[max_daily_capacity] )
)

-- Uses two What-if parameters (Modeling → New parameter): Queue Share (0–1, default 0.2)
-- and Save Rate (0–0.6, default 0.25). Both are ASSUMPTIONS.
Saveable Revenue =
VAR OpenBookings = FILTER ( fact_bookings, fact_bookings[is_open] = TRUE () )
VAR TopN = ROUND ( [Queue Share Value] * COUNTROWS ( OpenBookings ), 0 )
VAR Worked = TOPN ( TopN, OpenBookings, fact_bookings[revenue_at_risk_gbp], DESC )
RETURN [Save Rate Value] * SUMX ( Worked, fact_bookings[revenue_at_risk_gbp] )
```

These are 16 measures plus the two What-if parameter measures. Each one matches a definition in
`docs/METRICS.md`.

## 4. Page layouts

Use a white canvas, one accent colour (`#2A78D6`) and red (`#D03B3B`) only for at-risk or lost amounts.
Titles state the insight, not just the label. Add a text box with *Synthetic data — portfolio project*
on every page.

### Page 1: Executive overview (Finance)
- **Slicers** across the top: Country, City, Intake, Channel.
- **KPI cards**: Booked Commission, Expected Net Commission, Revenue at Risk (subtitle: Share of Open
  Commission at Risk), Cancellation Rate, Lead to Booking Conversion.
- **Stacked column chart**:
  - axis `dim_intake[intake]`, sorted by `sort_order`
  - values Realised Commission and Lost Commission (closed intakes), Expected Net Commission and
    Revenue at Risk (open intake)
- **Clustered bar** of Revenue at Risk by `dim_city[city]`, sorted descending.

### Page 2: Revenue at risk and operations (Ops)
- **Table** (the call list):
  - rows: open bookings; columns `booking_id`, `dim_agent[agent_name]`, `dim_city[city]`,
    `commission_gbp`, `p_cancel`, `revenue_at_risk_gbp`, `visa_status_at_booking`, `deposit_paid`
  - visual filter: `is_open = True`
  - sorted by `revenue_at_risk_gbp`, descending
- **Bar** of Agent Load (days) by `dim_agent[agent_name]`, with a constant line at 1.
- **Card** Saveable Revenue, with the Queue Share and Save Rate slicers beside it.
- **Bar** of Cancellation Rate by `visa_status_at_booking`, with a small multiple by `dim_student[source_country]`.

### Page 3: Market and funnel (City managers)
- **Funnel**: Leads, then reached contacted, reached shortlisted, reached booked. Use measures counting
  each flag.
- **Line** of Cancellation Rate (rolling 4 weeks) by `dim_date[week_start]`.
- **Matrix**: rows `dim_city[city]`, columns `dim_intake[academic_year]`, values Bookings with a PG
  filter (`dim_student[level] = "PG"`), showing the 2025-26 drop outside London.
- **Bar** of Lead to Booking Conversion by `dim_channel[channel]`.

## 5. Reconcile before you share

These are the expected totals with no slicers applied, from the seed-20261031 build. Each comes from
the export files and matches the SQL library and `metrics.py`. If a card disagrees, the model has a
relationship or filter problem: fix that before publishing.

| Measure | Expected (all data) | Source |
|---|---:|---|
| Bookings | 18,242 | `v_clean_bookings` |
| Booked Commission | £17,587,316 | `sql/15_commission_by_intake.sql` |
| Realised Commission | £11,912,412 | `metrics.realised_commission_gbp` |
| Expected Net Commission | £561,969 | `sql/07_revenue_at_risk_by_city.sql` |
| Revenue at Risk | £141,049 | `sql/07_revenue_at_risk_by_city.sql` |
| Cancellation Rate | 28.9% | `metrics.cancellation_rate` |
| Leads | 59,459 | `fact_lead` |
| Lead to Booking Conversion | 30.9% | `metrics.lead_to_booking_conversion` |
| Median First Response (min) | 77 | `metrics.median_first_response_minutes` |
| Saveable Revenue (20% / 25%) | £15,806 | `metrics.saveable_revenue_gbp` |

Screenshots of the finished pages go in `dashboards/screenshots/`.
