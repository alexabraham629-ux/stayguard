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

### 2026-11-03 — Action-queue warning paired an agent with the wrong team
- What the AI produced: the overflow warning said most overflow sat with Gillian Jordan (UK North), then
  advised "reassign within ANZ (8 spare calls)". The advice came from the first overflow row, not from
  Gillian's own rows.
- How it was caught (manual review): reading the page in the browser; the agent and team did not match.
- Fix: the advice now comes from the most-overflowing agent's own rows ("reassign within UK North (48
  spare calls today)").
- Lesson / guardrail added: any sentence that joins two facts must take both from the same row or
  aggregate. Checked when reviewing each page.

### 2026-11-03 — Chart title overclaimed a weak effect
- What the AI produced: the budget-band chart was titled "...it shows up in cancellations instead",
  implying a strong effect. Cancellations only move from 29.9% to 27.6% across budget bands.
- How it was caught (manual review): comparing the title with the plotted values.
- Fix: the title now states the numbers ("lower-budget students cancel slightly more (29.9% vs 27.6%)").
- Lesson / guardrail added: insight titles are computed from the data and quote the numbers they rely
  on, rather than characterising them.

### 2026-11-03 — Verifier's row-count check matched "country" as a count column
- What the AI produced: the sanity check looked for count columns with the pattern `count`, which also
  matches `country`, so it compared country names with a row count and crashed on any breakdown by country.
- How it was caught (test): `test_grouped_canonical_metric` failed with a TypeError.
- Fix: whole-word patterns (`^count`, `_count$`, `bookings`, `leads`, ...) applied to numeric columns only.
- Lesson / guardrail added: column-name heuristics are tested on real breakdown queries, not just
  single-number answers.

### 2026-11-03 — 0.5% tolerance let a duplicate-inflated count pass as correct
- What the AI produced: the verifier and the eval grader compared every number within 0.5%. A booking
  count taken from raw `fact_booking` (duplicates included) is off by about 0.5%, so the "careless model"
  answer to Q08 was graded correct and not flagged.
- How it was caught (test): `test_eval_with_a_careless_model_is_caught_by_the_verifier`, an offline run of
  the eval with a fake model that falls into each trap on purpose.
- Fix: whole numbers must match exactly; the 0.5% tolerance applies to rates and money only (ADR-026).
- Lesson / guardrail added: the eval harness is tested with deliberately wrong answers, so a lenient
  grader or verifier fails a test instead of inflating the score.

### 2026-11-03 — Stale SDK knowledge: MCP 1.x names used against the 2.x SDK
- What the AI produced: CLAUDE.md (and the model's own prior) named FastMCP and the 1.x field names
  `readOnlyHint` and `isError`. The installed MCP SDK is 2.3, where FastMCP is `MCPServer` and fields
  are snake_case. The server's annotations happened to load through aliases, but the test read
  `tool.annotations.readOnlyHint` and `result.isError`.
- How it was caught (inspection + test): the server import was checked against the installed package
  before writing code, which surfaced the rename. The stdio end-to-end test then failed with
  `AttributeError: ... Did you mean 'read_only_hint'?`.
- Fix: `MCPServer`, `read_only_hint` / `destructive_hint`, `is_error` (ADR-028).
- Lesson / guardrail added: check third-party APIs against the installed version (signatures, rename
  notices) before relying on remembered names. An end-to-end test against the real SDK is what caught
  the rest.

### 2026-11-03 — Money axes rounded to one significant figure
- What the AI produced: chart axes used Plotly's `,.0s` tick format, which rounds to one significant
  figure. On the What-If waterfall (values £520k–£600k), three different gridlines were all labelled
  "£600k" and two "£500k", which misstates the scale.
- How it was caught (manual review): reading the screenshots taken for the README. The same format
  looked fine on Home, where the values are round millions.
- Fix: `.3~s` (three significant figures, trailing zeros trimmed) on every money axis.
- Lesson / guardrail added: charts are reviewed as rendered images, not just as passing tests; a chart
  that renders without error can still mislead.

### 2026-11-04 — AI Audit counted MCP queries as failed verifications ("0% verified")
- What the AI produced: the AI Audit page computed "Answers auto-verified" over every request that was
  not `blocked` or `error`. When Phase 7 added MCP logging with a new status, `ran`, the denominator was
  not updated. MCP queries never go through the verifier, so the page reported "0% of answered
  questions passed independent verification" when the verifier had in fact checked nothing.
- How it was caught (manual review): reading the page while taking the README screenshot. The audit log
  held 8 MCP guardrail blocks and 1 MCP query, and no Ask the Data answers at all.
- Fix: `verified_share()` in `stayguard.ai.audit` counts only verifier statuses (`verified`,
  `mismatch`, `unverifiable`) and returns None when there are none; the page then shows "—" and says
  what the log holds. A unit test covers both cases.
- Lesson / guardrail added: when a new status value is added, re-check every place that filters on
  that column. Exclusion lists ("everything except blocked/error") silently absorb new values;
  inclusion lists don't.
