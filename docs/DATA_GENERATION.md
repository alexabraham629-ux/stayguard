# Data generation

> **All data is synthetic.** No real company, student, agent or university data is used.
> University and agent names are fictional.

`make data` runs `python -m stayguard.generate`. It simulates the marketplace, writes CSVs to
`data/raw/`, builds `data/stayguard.duckdb` (tables, keys, views), and prints the data-quality
report. A 200-row sample of each table is committed in `data/raw/sample/`.

## Reproducibility

- **One global seed** (`project.seed` in `config/assumptions.yaml`). Each stage (dimensions, leads,
  bookings, interactions, data issues) gets its own random stream via `numpy.random.SeedSequence.spawn`,
  so changing one stage does not reshuffle the others.
- `data/raw/manifest.json` records row counts, the planted-issue counts, the ground-truth agent ids
  and a content fingerprint per table. `tests/test_generator.py` regenerates and compares.
- Full generation takes **about 5 seconds** (budget: 60 s).

## Snapshot and censoring

"Today" inside the data is **2026-10-31** (data extracted at 00:00). Every lead's full lifecycle is
simulated, then **censored at the snapshot**: events after it are removed. So:

- Sep-2024 → Sep-2026 intakes are **closed**: every booking is `moved_in` or `cancelled`, and every
  lead is `booked` or `lost`.
- **Jan-2027** is **open**: bookings are `open` or `cancelled`, and leads may still be `new`,
  `contacted` or `shortlisted`. Only Jan-2027 leads created by 31 Oct exist (Nov–Dec leads are in the future).

## Tables (seed 20261031)

| Table | Rows | How it is simulated |
|---|---:|---|
| `dim_intake` | 6 | From `assumptions.yaml`: move-in date, academic year, open/closed at snapshot. |
| `dim_city` | 12 | 8 UK, 3 AU, 1 IE city. Currency and a fixed `fx_to_gbp` rate (ADR-009). |
| `dim_university` | 23 | 1–3 fictional universities per city. |
| `dim_property` | 263 | Operator type (PBSA chain / independent PBSA / HMO), room type, rent band by city, No Visa No Pay policy, cooling-off days, rating. |
| `dim_agent` | 29 | 5 teams, Faker names, languages, daily call capacity. |
| `dim_student` | 58,103 | Source country (mix depends on the market), UG/PG, budget, guarantor. |
| `fact_lead` | 59,459 | Volume per intake × city, monthly seasonality, channel, first-response time, then a 3-step funnel (contacted → shortlisted → booked). |
| `fact_booking` | 18,333 | Property chosen near the student's budget; tenancy, rent, GBV, commission (rate by operator type, an assumption); deposit; visa status. |
| `fact_cancellation` | 5,134 | Competing-risk model (below): reason, timing before move-in, refund. |
| `fact_interaction` | 155,338 | First response plus follow-ups on leads, post-booking touches until move-in, and a pre-arrival check-in for students who arrive. Simulated over each full lifecycle, then censored at the snapshot. |

`meta_build` holds the snapshot date, seed and generator version. Schema: `sql/schema/01_tables.sql`.

### Shared views (`sql/schema/02_views.sql`)

- `v_booking_duplicate_flags`: flags data-entry duplicates with `LAG()` over (student, property).
- `v_clean_bookings`: bookings without those duplicate rows. **Use this, not `fact_booking`.**
- `v_bookings_gbp`: clean bookings joined to intake, city, property, student and lead, with every money
  column converted to GBP (`*_gbp`) and cancellation details attached.

## How cancellations are simulated

Each booking gets an **intensity per cancellation reason**:
`visa_refused`, `no_place`, `cooling_off`, `found_cheaper`, `duplicate_booking`, `changed_plans` and `other`.

- The probability of cancelling is `1 − exp(−Σ intensities)`.
- The reason is drawn in proportion to the intensities.
- The cancellation date is drawn within the booking-to-move-in window, with a shape that depends on the
  reason. For example, visa refusals come late, duplicates come early, and cooling-off happens within the
  property's cooling-off days.

Each planted effect raises the intensity of specific reasons, so the effects are discoverable *and*
explainable by reason. Background constants (rent bands, country mix, base intensities) are in
`src/stayguard/generate/reference.py`. Planted effect sizes are in `config/assumptions.yaml`.

## Ground truth

These effects are planted on purpose, with noise. Phases 3–4 must **re-discover** them from the data.
`tests/test_ground_truth_data.py` checks that each one is visible in the raw data, and Phase 4 adds model-level
recovery tests. The figures in the last column are from the seed-20261031 build, measured on closed intakes
over clean bookings.

| # | Planted effect | Mechanism (parameter in `assumptions.yaml → generator.ground_truth`) | Observed in the data |
|---|---|---|---|
| 1 | Unresolved visa → much higher cancellation, strongest for Nigeria and Pakistan | `e1_visa`: visa_refused intensity by source country × status multiplier (not_applied 1.6, pending 1.0, granted 0.08) | Cancellation: not_applied 40.9%, pending 31.3%, granted 20.4%. Visa-refusal cancellations as a share of visa-required bookings: Pakistan 19.0%, Nigeria 18.1%, India 8.8%, China 3.1%, USA 1.9% |
| 2 | No deposit → higher cancellation | `e2_no_deposit_multiplier` = 1.9 on non-visa reasons | 38.9% without deposit vs 26.4% with |
| 3 | Booked > 180 days early → cancel more (shopping around); < 30 days → least | `e3_booking_lead_time` multipliers on found_cheaper, duplicate_booking, changed_plans; those reasons are timed early in the booking window | <30 d 15.3% · 30–89 d 22.1% · 90–179 d 28.8% · 180+ d 41.8%. Among bookings still alive 72 days before move-in, the direction flips (FINDINGS §3) |
| 4 | First response > 240 min → lower conversion | `e4_slow_response` logit penalties on shortlist and booking steps | Lead→booking 18.8% (slow) vs 35.6% |
| 5 | Ambassador and partner consultancy convert best, paid search worst | `e5_channel_logit` | Ambassador 38.6%, partner consultancy 36.9%, referral 34.2%, organic 30.6%, loan partner 30.3%, paid search 23.4% |
| 6 | PG demand softens in 2025-26, more in non-London UK | `e6_pg_demand_multiplier` thins PG leads | PG bookings 2024-25 → 2025-26: UK non-London 1,349 → 982 (−27%), London 552 → 537 (−3%), AU/IE 1,173 → 1,192 |
| 7 | Two agents over capacity; their bookings cancel more | `e7_overloaded_agents`: 3× lead share, 18–23 calls/day capacity, 2.5× slower response, 0.4× follow-ups, 1.7× non-visa cancellation intensity | Agents 10 and 13: cancellation 34.9% vs 28.1%; open-booking load 2.75 and 2.55 days of backlog (next highest 2.12) |
| 8 | Lead seasonality: Feb–Jul for Sep intakes, Sep–Nov for Jan intakes | `e8_lead_seasonality` monthly weights | 82.8% of Sep-intake leads created Feb–Jul; 69.5% of Jan-intake leads created Sep–Nov |

Baseline (closed intakes): lead→booking conversion **30.9%**, cancellation rate **28.9%**, and **975** open
Jan-2027 bookings to score.

**Confounding to be aware of:** partner consultancies and loan partners are used most by students from
higher visa-risk countries. A channel's cancellation rate therefore partly reflects its student mix.
Phase 4's multivariate model is how we separate the two.

## Planted data-quality issues

`sql/14_data_quality_report.sql` must catch each of these. `tests/test_quality.py` checks that the
detected count equals the planted count in the manifest.

| Check | Issue | Planted rows |
|---|---|---:|
| P1 | Duplicate booking rows: same student and property re-entered 1–47 h later (0.5%) | 91 |
| P2 | `first_response_minutes` missing although `contacted_at` is set (2% of contacted leads) | 1,117 |
| P3 | `cancelled_at` before `booked_at` | 12 |
| P4 | Bookings in AUD or EUR. Any total must convert with `fx_to_gbp`; summing local amounts is a bug | 6,766 |

The report also has 15 integrity rules that must be zero: keys, orphans, negative money, commission
arithmetic, currency coverage, status/cancellation agreement, no events after the snapshot, and so on.
All 15 pass.

Not every null is a defect. 3,617 leads were never contacted, so their missing first response is real
(check X01).

## Leakage trap (ADR-016)

Two signals, one legitimate and one not:

- **Engagement (legitimate as of a scoring date):** students who will later cancel answer fewer post-booking
  calls and messages (38% vs 62% positive outcomes).
- **Pre-arrival check-in (leaky):** in the last 14 days before move-in, every student who is actually arriving
  gets a check-in call. Like a real CRM process event, it only exists because of the outcome.

A model that uses interactions after its as-of date sees this check-in. On validation, PR-AUC jumps from
0.347 to 0.715 (docs/FINDINGS.md §4).

**The oracle check.** Because the data is synthetic, the generator also returns, in memory only, how each
open Jan-2027 booking really ends (`GeneratedData.hidden_truth`). It is never written to disk or to the
database. `tests/test_model.py` uses it to check the scores against the real future.

## Limitations

- **Fixed FX rates:** there is no currency movement over time.
- **Independent bookings:** a student's bookings are independent. `duplicate_booking` cancellations are
  labelled, but the "other" booking is not generated.
- **Simple pricing and policy:** rents and commission rates are stylised assumptions, not market data.
- **No supply constraint:** properties never sell out.
