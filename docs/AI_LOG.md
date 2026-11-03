# AI mistake log

Genuine mistakes made by AI (Claude Code during the build, or the app's NL-to-SQL in testing) that a test, reconciliation check or manual review caught. Entries are never invented; a phase with no mistakes adds nothing.

Format:

```
### YYYY-MM-DD — <short title>
- What the AI produced:
- How it was caught (test / reconciliation / manual review):
- Fix:
- Lesson / guardrail added:
```

---

### 2026-11-03 — NULL semantics turned a "rate of bookings" into a "share of cancellations"
- What the AI produced: While calibrating the generator, Claude Code wrote a diagnostic query
  `AVG((cancel_reason = 'visa_refused')::INT)` over `v_bookings_gbp` and read the result as "visa-refusal
  rate per booking". For non-cancelled bookings `cancel_reason` is NULL (LEFT JOIN), so the comparison is
  NULL and `AVG` silently skips those rows: the figure was the share *among cancellations* (Nigeria 49%),
  not among bookings (18%).
- How it was caught (manual review): the per-country numbers added up to far more visa cancellations
  than the total count of `visa_refused` rows, which is impossible.
- Fix: `AVG(COALESCE(cancel_reason = 'visa_refused', FALSE)::INT)`.
- Lesson / guardrail added: every rate in `tests/test_ground_truth_data.py` wraps nullable comparisons in
  `COALESCE(..., FALSE)`; the same rule goes into the NL→SQL prompt notes in Phase 6.

### 2026-11-03 — Stale number copied into documentation
- What the AI produced: `docs/DATA_GENERATION.md` stated "3,607 leads were never contacted", a figure
  from an earlier calibration run, after the generator had been re-tuned (actual: 3,617).
- How it was caught (reconciliation): before committing, every number in the doc was re-checked against
  the final build (`make quality`, check X01).
- Fix: corrected to 3,617.
- Lesson / guardrail added: docs are written from the final run only, and numbers are re-queried before
  commit. Phase 8 will add a test that checks the headline figures in the docs against the database.

### 2026-11-03 — Generated data broke the branding rule ("Amber Smith")
- What the AI produced: The generator used Faker for agent names without a guard, and one agent was named
  "Amber Smith". CLAUDE.md forbids the marketplace's name anywhere in the app; it would have appeared on
  the agent leaderboard.
- How it was caught (manual review): reading the first rows of `06_agent_leaderboard` while checking every
  query ran. The existing test only checked university names.
- Fix: `_agent_name()` rejects names containing a reserved word (`reference.RESERVED_NAME_WORDS`).
- Lesson / guardrail added: `test_no_brand_name_in_any_generated_text` scans every text column of every
  generated table.

### 2026-11-03 — Generator broke its own "simulate, then censor" rule for interactions
- What the AI produced: In Phase 2, post-booking (and lead) touches for open bookings were spread over
  booked_at → *snapshot* instead of the full lifecycle (booked_at → move-in) and then censored. Open bookings
  therefore had 2–3x the touch density of their historical equivalents (only 23% with no touch before the
  as-of point vs 51–63% in training intakes).
- How it was caught (reconciliation): the first trained model's mean p_cancel on open bookings was 25.4%
  vs 16.9% for the baseline. An oracle check against the generator's hidden true outcomes showed the
  real future rate was 17.8%, and a feature-by-intake comparison pinpointed the touch counts.
- Fix: simulate touches over the full lifecycle, then drop those after the snapshot. Model mean is now 19.7%
  vs 17.8% true; validation numbers did not change (only open bookings were affected).
- Lesson / guardrail added: `test_scores_match_the_hidden_future` (mean within 25% of the true rate,
  ROC-AUC > 0.65). Any train/score feature drift now shows up as a failing test.

### 2026-11-03 — The planted leakage trap did not trap
- What the AI produced: ADR-016's trap (students who will cancel reply less) was the same signal before
  and after the as-of point, so a model using all-time interactions scored *no better* than the honest one
  (PR-AUC 0.324 vs 0.347). The leakage demonstration demonstrated nothing.
- How it was caught (manual review of the first model report).
- Fix: added a pre-arrival check-in touch logged only for arriving students, a realistic process event
  tied to the outcome. Leaky PR-AUC is now 0.715.
- Lesson / guardrail added: `test_leakage_demo_shows_what_leakage_looks_like` asserts the leaky score is
  at least 1.5x the honest one, so the demo cannot silently stop working.

### 2026-11-03 — Perfectly collinear feature in the first model
- What the AI produced: features included both `days_booked_before_intake` and `days_since_booking`. With a
  fixed 72-day horizon the second is the first minus 72.
- How it was caught (manual review): identical permutation importances (0.017943 each).
- Fix: dropped `days_since_booking`.
- Lesson / guardrail added: features derived from the as-of horizon are reviewed for redundancy; noted in
  `features.py`.
