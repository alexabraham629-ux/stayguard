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
