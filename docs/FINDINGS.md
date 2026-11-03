# Findings and recommendations

> **Draft (Phase 4).** Synthetic data, portfolio project. Every number below comes from
> `make data` at seed 20261031: `python -m stayguard.model` output, the `model_*` tables, and the
> SQL library. Recommendations are completed in Phase 8.

## 1. The open intake (Jan-2027): what will land

| | GBP | Source |
|---|---:|---|
| Booked commission on open bookings | 703,019 | `07_revenue_at_risk_by_city` |
| **Expected Net Commission (ENC)** | **561,969** | `metrics.expected_net_commission_gbp` |
| Revenue at Risk | 141,049 | `metrics.revenue_at_risk_gbp` |
| Saveable revenue: work the top 20% of the queue at a 25% save rate (both assumptions) | 15,806 | `metrics.saveable_revenue_gbp` |

- **London carries 29.8% of revenue at risk** (£42,065), then Sydney (14.8%) and Melbourne (14.6%).
- The 975 open bookings have a mean predicted cancellation risk of **19.7%**.

## 2. The cancellation-risk model

**Set-up (ADR-005, ADR-019).** We predict whether a booking still alive 72 days before move-in
(where Jan-2027 is today) cancels before move-in.
- **Train:** Sep-2024 to Jan-2026.
- **Validate:** Sep-2026, chosen by time and never randomly.
- **Backtest:** Jan-2026, because the open intake is a January one.

Features are only what was known at booking, plus interactions *before* the as-of point.

**Validation (Sep-2026, 2,881 bookings, 15.2% cancel after the as-of point)**

| Model | ROC-AUC | PR-AUC | Brier | Lift, top decile | Commission saved working the top 20% |
|---|---:|---:|---:|---:|---:|
| Random calls | 0.500 | 0.152 | — | 1.00 | £22,654 |
| Segment-rate baseline (SQL, ADR-017) | 0.625 | 0.216 | 0.125 | 1.60 | £39,584 |
| Gradient boosting | 0.675 | 0.315 | 0.120 | 2.56 | £49,285 |
| **Logistic regression (chosen)** | **0.695** | **0.347** | **0.117** | **2.72** | **£52,085** |
| *Perfect foresight* | — | — | — | — | *£113,270* |

- **Logistic regression is chosen** on PR-AUC. It is also the easier model to explain.
- **It holds on the January backtest** (775 bookings): PR-AUC 0.403 vs 0.247 for the baseline.
- **Calibration is good.** Predicted risk matches observed risk in every tenth of the validation set to within
  3.3 percentage points, e.g. top tenth predicted 40.4% vs observed 41.3% (`model_calibration`).
- **The top risk decile holds 27.2% of all cancellations** (lift 2.72x).
- **Business value:** working the top 20% of the queue saves **2.3x** the commission of random calling, and
  32% more than the baseline.

**Oracle check (synthetic data only).** The generator knows how every open Jan-2027 booking really ends,
so we can score against that hidden truth without it reaching the database.
- **True future cancellation rate:** 17.8%.
- **Model mean:** 19.7%, against 16.9% for the baseline.
- **Ranking:** the model ranks far better than the baseline, with ROC-AUC 0.724 vs 0.582
  (`test_scores_match_the_hidden_future`).

## 3. What drives cancellation (and did we re-discover the planted effects?)

Permutation importance on validation (drop in PR-AUC when a feature is shuffled):

| Rank | Feature | Importance |
|---:|---|---:|
| 1 | Share of post-booking contacts the student answered (before as-of) | 0.083 |
| 2 | Number of post-booking contacts (before as-of) | 0.080 |
| 3 | Days booked before move-in | 0.054 |
| 4 | Visa status at booking | 0.048 |
| 5 | Source country | 0.040 |
| 6 | Deposit paid | 0.019 |
| 8 | Agent load vs team | 0.004 |

Counterfactual checks hold everything else fixed and change one thing (`model_effect_recovery`). **All five
planted cancellation effects are recovered:**

| Planted effect | Change | Mean predicted risk | |
|---|---|---|---|
| 1. Visa status | granted → pending | 10.5% → 16.4% (+56%) | ✅ |
| 1. Source country | China → Nigeria (visa pending) | 12.2% → 25.5% (+109%) | ✅ |
| 2. Deposit | paid → not paid | 14.0% → 18.9% (+35%) | ✅ |
| 3. Lead time | booked 90 → 200 days before move-in | 21.3% → 10.7% (−50%) | ✅ (see below) |
| 7. Agent overload | team-average load → 2.5x | 14.7% → 21.4% (+46%) | ✅ |

Effects 4, 5, 6 and 8 (response time, channel, PG demand, seasonality) are about conversion and demand. The
SQL library re-discovers them (`08`, `12`, `11`, `01`), and `tests/test_ground_truth_data.py` checks them.

### Insight: early bookers are risky early, not late

Bookings made 180+ days before move-in cancel at 41.8% overall, against 15.3% for under 30 days.
That is the planted effect, visible in the raw data. But those extra cancellations (found cheaper, duplicate
booking) happen soon after booking. **Among bookings still alive 72 days before move-in, early bookers are
the *lower*-risk group:** Sep intakes 13.0% for 180+ days vs 18.4% for under 90 days.

- **What would go wrong:** an unconditional model or rule ("booked 7 months early = risky") would send
  agents to the wrong students at exactly the point in the cycle when the call list is used.
- **What we did:** the action queue's reason codes leave this flag out (ADR-020).

## 4. Leakage: what it would have looked like

Real CRMs log a pre-arrival check-in only for students who are actually moving in. If interaction features
ignore the as-of cut-off, the same model scores **PR-AUC 0.715 and ROC-AUC 0.875** on validation, against
0.347 and 0.695 for the honest model.
- **It would look like a breakthrough,** but it can't work in production: on 31 October nobody has had their
  pre-arrival call yet.
- **Guards:** `assert_no_leakage` and `tests/test_model.py` guard the feature list. A test also keeps the
  demonstration itself working.

## 5. Draft recommendations (to refine in Phase 8)

1. **Ops: call the risk-ranked queue, not the oldest bookings.** Each agent's highest expected-loss bookings
   come first, within daily capacity (`13_action_queue`): 776 calls fit today and 199 overflow.
2. **Ops: rebalance agents 10 and 13.** They carry 2.5–2.75 days of backlog (next highest 2.12), respond
   slower, and their students cancel more (34.9% vs 28.1%). Reassign the overflow within UK North.
3. **Finance: plan on ENC (£562k), not booked commission (£703k),** for the January intake. Track
   Revenue at Risk weekly.
4. **Product / policy: push for deposits and visa progress.** No deposit and an unresolved visa are the
   strongest booking-time risk factors after engagement. Test a deposit-required policy for high-risk
   segments in the What-If Simulator (Phase 5), keeping in mind that its uplift is an assumption.
5. **Ops: treat silence as a signal.** Students who have not replied since booking are the top model
   driver. A "no reply since booking" flag is in the reason codes.
