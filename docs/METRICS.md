# Metric dictionary

> Synthetic data, portfolio project. Assumptions are marked as such and live in `config/assumptions.yaml`.

**Source of truth.** Every metric is implemented in `src/stayguard/metrics.py`, in pandas and
independently of the SQL library. `tests/test_sql.py` reconciles each SQL file against it within
0.5% (`ai.verification_tolerance`). Counts and rates must match exactly, and they do. The AI verifier in
Phase 6 uses the same functions.

**Conventions**
- **Money** is always in **GBP**. Every booking is converted with its city's fixed `fx_to_gbp` rate in
  `v_bookings_gbp` before any sum. Summing `*_local` columns across countries mixes currencies and is a bug;
  `test_gbp_conversion_differs_from_naive_local_sum` guards against it.
- **Bookings** means clean bookings (`v_clean_bookings`), with data-entry duplicates removed (ADR-008).
- **Closed intake:** an intake whose move-in date is on or before the 2026-10-31 snapshot. Outcome rates
  (cancellation, conversion) use closed intakes only, because open-intake outcomes are not final.
- **Open bookings:** Jan-2027 bookings that have not cancelled. They are what ENC, Revenue at Risk and the
  action queue are about.
- **Filters:** every function takes `Filters(countries, cities, intakes, channels)`, the app's sidebar.

## Revenue

| Metric | Definition | Formula | Scope | `metrics.py` | SQL | Owner |
|---|---|---|---|---|---|---|
| **GBV** | Gross booking value | Σ weekly_rent × tenancy_weeks × fx_to_gbp | All clean bookings | `gbv_gbp` | `v_bookings_gbp.gbv_gbp` | Finance |
| **Booked Commission** | Commission booked at the time of booking | Σ GBV × commission_rate. Rate by operator type: PBSA chain 8%, independent PBSA 11%, HMO 14% (**assumption**) | All clean bookings | `booked_commission_gbp` | `02_weekly_booking_velocity` | Finance |
| **Realised Commission** | Commission that actually landed | Σ commission where status = `moved_in` | Moved-in bookings | `realised_commission_gbp` | `12_channel_unit_economics` | Finance |
| **p_cancel** | Probability an open booking cancels before move-in, given it has survived to today | From `scored_bookings`. Phase 3: survival-aware segment baseline (ADR-017). Phase 4: ML model | Open bookings | (column) | `schema/03_baseline_scores.sql` | Analytics |
| **Expected Net Commission (ENC)** ⭐ | **North star.** Commission we expect to land from the open intake | Σ commission × (1 − p_cancel) | Open bookings | `expected_net_commission_gbp` | `07_revenue_at_risk_by_city` | Finance |
| **Revenue at Risk** | Commission we expect to lose to cancellations | Σ commission × p_cancel | Open bookings | `revenue_at_risk_gbp` | `07_revenue_at_risk_by_city` | Finance |
| **Saveable Revenue** | Commission the team can realistically save by calling the top of the queue | Revenue at Risk in the top-N queue × save rate. Defaults: N = 20% of open bookings, save rate 25% (both **assumptions**) | Open bookings | `saveable_revenue_gbp` | `13_action_queue` (`saveable_if_called_gbp`) | Ops |

ENC + Revenue at Risk = booked commission on open bookings (tested).

## Cancellation

| Metric | Definition | Formula | Scope | `metrics.py` | SQL | Owner |
|---|---|---|---|---|---|---|
| **Cancellation Rate** | Share of bookings that cancelled | cancelled ÷ all clean bookings | Closed intakes | `cancellation_rate` | `03_cohort_cancellation_curve` (final cumulative point), `05_rolling_cancellation_rate` | Revenue |
| **Survival Rate** | Share of bookings that reached move-in | 1 − cancellation rate | Closed intakes | `survival_rate` | `03_cohort_cancellation_curve` | Revenue |
| **4-week rolling cancellation rate** | Trend of the above by booking week | Pooled: Σ cancellations ÷ Σ bookings over the current and 3 previous weeks. The simple average of weekly rates is shown too, but over-weights small weeks | Closed intakes, per city | `weekly_cancellation_rates` | `05_rolling_cancellation_rate` | Revenue |

Notes:
- A cancellation timestamped before its booking (a planted issue, 12 rows) still counts in the rate, but is
  excluded from timing analyses (`has_invalid_cancel_timestamp`).
- `duplicate_booking` as a cancellation *reason* is a real business event and stays in the rate. It is not
  the same as a duplicate data row (ADR-008).

## Funnel & operations

| Metric | Definition | Formula | Scope | `metrics.py` | SQL | Owner |
|---|---|---|---|---|---|---|
| **Lead→Booking Conversion** | Share of leads that booked | leads with status `booked` ÷ leads | Closed intakes (cohort = intake; the funnel query also splits by city) | `lead_to_booking_conversion` | `01_funnel_by_city_intake`, `12_channel_unit_economics` | City managers |
| **Median First Response** | Typical minutes from enquiry to first agent contact | median(first_response_minutes) | Leads with a recorded time | `median_first_response_minutes` | `06_agent_leaderboard` | Ops |
| **Missing first response** | Contacted leads with no recorded response time: a data gap, reported separately, never imputed | count(contacted_at set AND first_response_minutes NULL) | All leads | `missing_first_response_count` | `14_data_quality_report` (P2) | Analytics |
| **Agent Load** | **Days of backlog** (ADR-007) | open bookings ÷ max_daily_capacity. Above 1 = cannot clear the queue in a day | Per agent | `agent_load` | `06_agent_leaderboard`, `13_action_queue` | Ops |
| **Response SLA breach** | Lead answered too slowly | first_response_minutes > 240 (**assumption**, `meta_assumption`) | Leads | (in query) | `08_response_time_vs_conversion` | Ops |

## Where the assumptions come from

SQL never hard-codes a business assumption. The build copies the ones the SQL needs into
`meta_assumption`, and queries read them from there:

| `meta_assumption.name` | Value | Used by |
|---|---|---|
| `late_first_response_minutes` | 240 | `08_response_time_vs_conversion` |
| `intervention_save_rate` | 0.25 | `13_action_queue` |
| `queue_top_share` | 0.20 | `metrics.saveable_revenue_gbp` default |

Current values of these metrics are on the app's pages, each with its SQL file. This dictionary holds
definitions only, so it cannot go stale.
