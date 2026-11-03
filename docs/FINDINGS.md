# Findings and recommendations

> Synthetic data, portfolio project. Every number below comes from code run on the seed-20261031 build
> (`make data`): the SQL library, `metrics.py`, the model's `model_*` tables, the What-If simulator and
> `notebooks/01_eda.ipynb`. Assumptions (commission rates, 25% save rate, 20% queue share) are labelled.

## Executive summary

- **£562k of the £703k still open for Jan-2027 is expected to land.** £141k (20.1%) is at risk, close to
  the 19.4% Jan-2026 actually lost from the same point. London carries 30% of it.
- **Five of seven reasons explain 88.7% of cancellations:** found cheaper, visa refused, changed plans,
  duplicate booking and no place.
- **Visa status and home country are the sharpest risk signals at booking.** Pakistani and Nigerian
  students who had not applied for a visa cancel 55% and 52% of the time.
- **Demand is softening where expected:** UK postgraduate bookings outside London fell 27% in 2025-26,
  London 2%, and Australia/Ireland grew 2%.
- **Three levers could add about £28k (+5.0%) to Jan-2027's expected commission:** a risk-ranked call
  queue, chasing deposits, and a response-time target. This is a projection from labelled assumptions.

## 1. The open intake (Jan-2027): what will land

| | GBP | Source |
|---|---:|---|
| Booked commission, all Jan-2027 bookings so far | 821,305 | `sql/15_commission_by_intake.sql` |
| Commission still open (not yet cancelled) | 703,019 | `sql/07_revenue_at_risk_by_city.sql` |
| **Expected Net Commission (ENC)** | **561,969** | `metrics.expected_net_commission_gbp` |
| Revenue at Risk | 141,049 | `metrics.revenue_at_risk_gbp` |

- **Bookings are ahead of last year:** booked commission is **+25.6%** vs Jan-2026 at the same point
  (£653,799).
- **Expected commission is ahead too:** ENC is **+25.0%** above what Jan-2026 actually landed from
  bookings made by this point (£449,424).
- **The risk share is similar to last year:** 20.1% of still-live commission is at risk, vs 19.4% that
  Jan-2026 really lost from this point. The growth is volume, not lower risk.
- **Where the risk sits:** London carries **29.8%** of revenue at risk (£42,065), then Sydney (14.8%)
  and Melbourne (14.6%).

## 2. The cancellation-risk model

**Set-up (ADR-005, ADR-019).** The model predicts whether a booking still alive 72 days before move-in,
which is where Jan-2027 is today, cancels before move-in.
- **Train:** Sep-2024 to Jan-2026.
- **Validate:** Sep-2026, chosen by time and never randomly.
- **Backtest:** Jan-2026.

Features are only what was known at booking, plus contacts before that point.

**Validation (Sep-2026, 2,881 bookings, 15.2% cancel after the as-of point)**

| Model | ROC-AUC | PR-AUC | Brier | Lift, top decile | Commission saved working the top 20% |
|---|---:|---:|---:|---:|---:|
| Random calls | 0.500 | 0.152 | — | 1.00 | £22,654 |
| Segment-rate baseline (SQL, ADR-017) | 0.625 | 0.216 | 0.125 | 1.60 | £39,584 |
| Gradient boosting | 0.675 | 0.315 | 0.120 | 2.56 | £49,285 |
| **Logistic regression (chosen)** | **0.695** | **0.347** | **0.117** | **2.72** | **£52,085** |
| *Perfect foresight* | — | — | — | — | *£113,270* |

- **Logistic regression is chosen** on PR-AUC, and it is also the easier model to explain.
- **It holds on the January backtest** (775 bookings): PR-AUC 0.403 vs 0.247 for the baseline.
- **Calibration is good:** predicted and observed risk agree within 3.3 points in every tenth of the
  validation set.
- **The riskiest tenth holds 27.2% of all cancellations.**
- **Business value:** working the top 20% saves 2.3x the commission of random calling, and 32% more than
  the baseline rule.

**Oracle check (synthetic data only).** The generator knows how every open Jan-2027 booking really ends.
- **True future cancellation rate:** 17.8%.
- **Model mean:** 19.7%, against 16.9% for the baseline.
- **Ranking:** ROC-AUC 0.724 vs 0.582 (`tests/test_model.py::test_scores_match_the_hidden_future`).

## 3. What drives cancellation, and did we re-discover the planted effects?

**Permutation importance (validation):** the strongest drivers are engagement (the share of post-booking
contacts answered: 0.083; the number of contacts: 0.080), then how early the student booked (0.054),
visa status (0.048), home country (0.040) and deposit (0.019).

**All five planted cancellation effects are recovered** (counterfactual checks, `model_effect_recovery`):

| Planted effect | Change | Mean predicted risk |
|---|---|---|
| 1. Visa status | granted → pending | 10.5% → 16.4% (+56%) |
| 1. Home country | China → Nigeria (visa pending) | 12.2% → 25.5% (+109%) |
| 2. Deposit | paid → not paid | 14.0% → 18.9% (+35%) |
| 3. Lead time (given survival to 72 days out) | booked 90 → 200 days before | 21.3% → 10.7% (−50%) |
| 7. Agent overload | team-average load → 2.5x | 14.7% → 21.4% (+46%) |

The SQL library re-discovers the other three effects (§5); `tests/test_ground_truth_data.py` checks them.

**Raw cancellation rates (intakes that have moved in):**
- **No deposit:** 38.9%, vs 26.4% with a deposit.
- **By visa status:** not applied 40.9%, pending 31.3%, granted 20.4%.
- **Worst segments:** Pakistan 55.1% (visa not applied, 263 bookings), of which 33.5% was a visa refusal;
  Nigeria 52.2% (312 bookings).

### Insight: early bookers are risky early, not late

Bookings made 180+ days before move-in cancel at 41.8% overall, against 15.3% for under 30 days. But
their extra cancellations (found cheaper, duplicate booking) happen soon after booking, and 43% of all
cancellations happen within 30 days of booking. **Among bookings still alive 72 days before move-in,
early bookers are the *lower*-risk group:** Sep intakes 13.0% vs 18.4% for those booked under 90 days out.

A rule like "booked 7 months early = call them" would point agents at the wrong students exactly when
the call list is used, so the action queue leaves it out (ADR-020).

## 4. Leakage: what it would have looked like

Real CRMs log a pre-arrival check-in only for students who are actually moving in. If the model's
interaction features ignore the as-of cut-off, validation PR-AUC jumps from **0.347 to 0.715** and
ROC-AUC from 0.695 to 0.875. That looks like a breakthrough, but it can't work in production: nobody has
had their pre-arrival call on 31 October. Guards: `assert_no_leakage`, a test for each leaky column, and a
test that keeps the demonstration honest.

## 5. Funnel and market

- **The biggest funnel leak is contact → shortlist:** 43% of students we reach never shortlist a room.
  From enquiry, 94% are contacted, 54% shortlist, 31% book and 22% move in (closed intakes, 55,382
  enquiries).
- **Speed matters:**
  - **Conversion:** leads answered in up to 206 minutes (the fastest four fifths) convert at 35–37%; the
    slowest fifth converts at **21.2%**.
  - **SLA:** 83.5% of leads are answered within 240 minutes today. Leads answered in time convert at
    35.6%, vs 18.8% for late ones.
- **Channels differ in value, not just volume.** Landed commission per lead:

  | Channel | Value per lead | Conversion |
  |---|---:|---:|
  | Ambassador | **£264** | 38.6% |
  | Partner consultancy | £245 | 36.9% |
  | Referral | £244 | 34.2% |
  | Organic | £216 | 30.6% |
  | Loan partner | £204 | 30.3% |
  | Paid search | **£167** | 23.4% |

  Partner and loan-partner students cancel more (31.9%, 31.5%), partly because they come from higher
  visa-risk countries. That is confounding, not necessarily a channel effect.
- **PG demand softening (like-for-like, `sql/11`):**

  | Segment | 2024-25 → 2025-26 PG bookings | Change |
  |---|---|---:|
  | UK non-London | 1,228 → 892 | **−27%** |
  | London | 511 → 500 | −2% |
  | AU/IE | 1,081 → 1,100 | +2% |

- **Budget barely moves conversion:** within 0.6 points across budget bands. Lower-budget students
  cancel slightly more (29.9% vs 27.6%).
- **Enquiries peak about 5–6 months before move-in:** Mar–May for September, Sep–Oct for January.
- **Currency discipline matters:** adding local GBP, AUD and EUR amounts together would overstate
  commission by **30.8%** (£23.0m vs the correct £17.6m).

## 6. Operations

- **Two agents are overloaded:** Gillian Jordan (2.75 days of backlog) and Jacqueline Grant (2.55), both
  in UK North, against a median of 0.90. They respond slower, and their students cancel more (34.5% and
  35.3% vs 28.1% for everyone else).
- **Today's call list:** 776 of 975 calls fit in agents' capacity and 199 overflow. The queue suggests
  reassigning the overflow within each team.

## 7. Recommendations

Impacts are What-If projections on Jan-2027 (`src/stayguard/sim/whatif.py`) unless stated. Projections
rest on labelled assumptions, not causal estimates.

| # | Recommendation | Owner | Expected impact | Evidence |
|---|---|---|---|---|
| 1 | Work the risk-ranked call queue every day: the top 20% of open bookings by expected loss (195 calls), not the oldest bookings. | Ops | **+£15,806 ENC** at a 25% save rate (assumption) | Model validation: 2.3x random, 1.3x baseline (§2) |
| 2 | Chase deposits on the 178 open bookings without one, starting with visa-pending students from high-risk countries. | Ops + Product | **+£4,563 ENC** if half pay; test a deposit-required policy for high-risk segments | No deposit: 38.9% vs 26.4% cancel (§3) |
| 3 | Set and monitor a 240-minute first-response target for 95% of leads (today 83.5%), starting with UK North. | Ops | **+£8,293 ENC** from the 738 pipeline leads | Late leads convert at 18.8% vs 35.6% (§5) |
| 4 | Rebalance UK North: move overflow from Gillian Jordan and Jacqueline Grant to teammates with spare calls. | Ops | Brings their students' 34–35% cancellation towards the 28% norm | §6 |
| 5 | Plan January cash on ENC (£562k), not booked commission (£821k), and review Revenue at Risk weekly. | Finance | Avoids a £259k gap between booked and expected | §1 |
| 6 | Shift acquisition budget from paid search towards ambassador, referral and partner channels; cap partner spend in visa-risky markets. | Marketing | Each lead moved from paid search to ambassador is worth about £97 more landed commission | §5 |
| 7 | In UK non-London cities, re-target postgraduate supply and marketing for the softer 2025-26 market; protect London. | City managers | Responds to the −27% PG drop outside London | §5 |

Recommendations 1–3 together project **+£28,133 (+5.0%) ENC**. That is less than their simple sum,
because chased deposits reduce the risk the queue can save; the simulator applies them in order.

## 8. Limitations

- **The data is synthetic.** Effects were planted, so recovering them shows the method works, not that
  the business behaves this way.
- **Simplified world:** fixed FX rates; stylised rents and commission rates (an assumption by operator
  type); no supply constraint.
- **What-If levers are not causal estimates.** The deposit and response-time levers read effects off
  observational data, and the save rate is an assumption.
- **The model is scored at one horizon** (72 days before move-in), and the scores should be refreshed as
  the intake gets closer.
- **AI layer:** verified offline only. The live 15-question eval has not been run yet because no API key
  is available (ADR-027).
