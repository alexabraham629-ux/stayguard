# Decisions log (ADR-style)

Each entry: context, decision, consequences. Newest at the bottom. Decisions ADR-001 to ADR-013
were agreed in Phase 0 (2026-11-03).

---

### ADR-001 — Tech stack as specified in CLAUDE.md §2
- **Context:** The project must showcase SQL, Python, dashboards and a verified AI layer, and deploy free.
- **Decision:** Python, uv, DuckDB, pandas/numpy/Faker, scikit-learn, plotly, Streamlit, Anthropic SDK,
  sqlglot, MCP (FastMCP), pytest, ruff. Deploy to Streamlit Community Cloud.
- **Consequences:** Single-file analytical DB, no server to run. Any new dependency needs approval.

### ADR-002 — Python 3.12, pinned through uv
- **Context:** The machine has Python 3.14; Streamlit Community Cloud and some scientific wheels
  are best supported on 3.12.
- **Decision:** `.python-version` = 3.12 and `requires-python = ">=3.12,<3.13"`. uv installs and
  manages 3.12 separately from the system Python.
- **Consequences:** Same interpreter locally and in deployment. Upgrade later as one deliberate change.

### ADR-003 — GNU make on Windows; shell-neutral recipes
- **Context:** CLAUDE.md specifies `make` targets; Windows has no make by default.
- **Decision:** Install GNU make via winget (`ezwinports.make`). Every recipe only calls `uv …`,
  so it behaves the same under cmd.exe and sh.
- **Consequences:** No `rm -rf`, redirects or shell-specific syntax in the Makefile; file operations
  go in Python scripts.

### ADR-004 — Approved additions to the dependency list
- **Context:** §14 requires approval for dependencies not listed in §2.
- **Decision:** Add `pyyaml` (reads `config/assumptions.yaml`) and `ipykernel` (dev only, for the
  EDA notebook). Build backend is `uv_build` (part of the uv toolchain).
- **Consequences:** `requirements.txt` is generated from `uv.lock` with `make reqs`; a test fails if
  it falls out of sync with `pyproject.toml`.

### ADR-005 — Score open bookings conditional on survival to the snapshot
- **Context:** On the snapshot date every open Jan-2027 booking has already survived some days.
  A model trained on all historical bookings predicts cancellation *from booking*, overstating risk
  for older bookings and inflating Revenue at Risk.
- **Decision:** Build training rows "as of" the same days-before-intake as the snapshot: keep only
  bookings still alive at that point; target = cancelled after that point. Features remain
  knowable at booking time, plus `days_since_booking`.
- **Consequences:** Slightly smaller training set; p_cancel is calibrated for the population we
  actually act on. Documented in Phase 4 and `FINDINGS.md`.

### ADR-006 — Booking status values
- **Context:** §4 lists `confirmed`, `open`, `cancelled`, `moved_in`; "confirmed" and "open" overlap.
- **Decision:** Persist three values: `open` (intake not started, not cancelled — Jan-2027 only),
  `moved_in` (survived to intake start), `cancelled`. `confirmed` is not stored.
- **Consequences:** Closed intakes contain only `moved_in` and `cancelled`; cancellation rate has an
  unambiguous denominator.

### ADR-007 — Agent Load is "days of backlog"
- **Context:** "Open bookings ÷ max_daily_capacity" divides a stock by a daily flow.
- **Decision:** Keep the formula, label it **days of backlog**. The action queue assigns at most
  `max_daily_capacity` calls per agent per day.
- **Consequences:** Load > N days flags an overloaded agent; units are explicit in METRICS.md.

### ADR-008 — Two kinds of duplicates, handled differently
- **Context:** The planted data-quality issue (same booking entered twice within 48 h) is different
  from a real student holding two bookings and cancelling one (reason `duplicate_booking`).
- **Decision:** `v_clean_bookings` removes only the data-entry duplicates (keep the earliest row).
  `10_duplicate_booking_detection` reports both kinds, labelled separately.
- **Consequences:** Business cancellations with reason `duplicate_booking` stay in cancellation rates.

### ADR-009 — Fixed FX rates
- **Context:** Money is in GBP, AUD and EUR; totals must be converted.
- **Decision:** One fixed `fx_to_gbp` rate per currency for the whole period, in `assumptions.yaml`.
- **Consequences:** No FX noise in trends; this limitation is stated in the README.

### ADR-010 — AI audit log in a separate database file
- **Context:** The app and MCP server open `stayguard.duckdb` read-only; DuckDB cannot mix a writer
  and read-only connections on one file.
- **Decision:** Store `ai_audit` in `data/ai_audit.duckdb`, attached for the audit page.
- **Consequences:** On Streamlit Community Cloud the audit log resets on restart (documented limitation).

### ADR-011 — Deployed app builds its data on first boot
- **Context:** The DuckDB file is gitignored; the deploy needs data.
- **Decision:** On first boot the app runs the deterministic generator and model, cached with
  `st.cache_resource` (target < 90 s).
- **Consequences:** No binary in git; the first visitor waits once per container start.

### ADR-012 — Mermaid diagrams via mermaid.js in a component
- **Context:** Streamlit does not render Mermaid natively.
- **Decision:** Render with `streamlit.components.v1.html` loading mermaid.js from a CDN.
- **Consequences:** No new Python dependency; diagram needs internet access in the browser.

### ADR-013 — Public demo runs in Demo mode only
- **Context:** A public deploy with an API key carries cost and abuse risk.
- **Decision:** The public deploy has no key and serves pre-recorded, verified answers from
  `data/demo_cache.json`. Live AI runs locally (recorded for the README GIF). The per-session rate
  limit still exists for anyone running with a key.
- **Consequences:** Zero API spend on the public demo; Demo-mode banner is always visible there.

### ADR-014 — Schema additions beyond CLAUDE.md §4 (Phase 2)
- **Context:** The funnel query needs the stage each lead reached; interactions belong to a lead *or* a
  booking; queries need intake dates and the snapshot date without hard-coding them.
- **Decision:** Add `dim_intake` (move-in date, academic year, open/closed), `meta_build` (snapshot date,
  seed), `fact_lead.contacted_at` and `shortlisted_at`, and give `fact_interaction` two nullable keys
  (`lead_id`, `booking_id`) with a CHECK that exactly one is set. Enumerated columns get CHECK constraints.
  The student's visa requirement stays internal to the generator (visible as `not_required` visa status).
- **Consequences:** Funnel stages come from timestamps, so `first_response_minutes` can be cross-checked
  against `contacted_at`. The spec's columns are all present and unchanged.

### ADR-015 — Generator design
- **Context:** The planted effects must be discoverable, explainable, reproducible and fast.
- **Decision:** Simulate full lifecycles, then censor at the snapshot (2026-10-31 00:00). Cancellation is a
  competing-risk model with one intensity per reason. Planted effect sizes, volumes and data-quality rates
  live in `assumptions.yaml`; background calibration constants live in `generate/reference.py`. Each stage
  has an independent random stream (`SeedSequence.spawn`). The two overloaded agents are junior
  (18–23 calls/day) so they top Agent Load, as effect 7 requires.
- **Consequences:** Every effect maps to a reason code, which helps the action queue's reason codes later.
  Generation takes about 5 s.

### ADR-016 — Post-booking interactions as a deliberate leakage trap
- **Context:** In real CRMs, students who are about to cancel stop replying. That signal is legitimate
  "as of" a scoring date and leaky after it.
- **Decision:** Students who will cancel get fewer positive interaction outcomes (38% vs 62%).
- **Consequences:** Phase 4 must build interaction features only from touches before the as-of date
  (ADR-005), and the leakage test must fail if later touches are used.

### ADR-017 — Survival-aware SQL baseline scores until the ML model exists (Phase 3)
- **Context:** Queries 07 (Revenue at Risk) and 13 (action queue) need `p_cancel` for open bookings, but
  the model is Phase 4.
- **Decision:** `sql/schema/03_baseline_scores.sql` writes `scored_bookings` at build time. For each segment
  (visa status × deposit × lead-time band), it takes the historical rate at which closed-intake bookings
  that were still alive at the same days-before-move-in as today went on to cancel (ADR-005). Thin
  segments (< 50) fall back to the overall rate. `model_version = 'baseline_segment_rate_v1'`.
- **Consequences:** All 14 queries are testable now. Phase 4 overwrites the table with the ML model and must
  beat this baseline on the validation intake, which gives a fair benchmark.

### ADR-018 — metrics.py in pandas, independent of the SQL; assumptions table for SQL
- **Context:** Reconciling SQL against a metrics module that runs the same SQL proves nothing.
- **Decision:** `metrics.py` computes every canonical metric in pandas from the shared views. SQL reads
  business assumptions (SLA minutes, save rate) from a `meta_assumption` table populated from
  `assumptions.yaml` at build time.
- **Consequences:** Two independent implementations must agree (`tests/test_sql.py`), and there is still
  one place to change an assumption.

**ADR-016 amendment (Phase 4):** The engagement signal alone barely leaked, because it is the same before and
after the as-of point (the leaky demo scored PR-AUC 0.324 vs 0.347 honest). A pre-arrival check-in touch,
logged only for students who arrive, now makes the trap real (leaky PR-AUC 0.715).

### ADR-019 — Cancellation model: logistic regression, chosen on validation, refit for scoring
- **Context:** CLAUDE.md §7: LR baseline plus HistGradientBoosting, time-based split, pick by PR-AUC.
- **Decision:** Fit both on Sep-2024 to Jan-2026; pick on Sep-2026 PR-AUC (LR 0.347 vs HGB 0.315); confirm on a
  Jan-2026 backtest because the open intake is a January one. Then refit the chosen model on all closed
  intakes and score Jan-2027 as of the snapshot. `days_since_booking` is excluded because it equals days
  before move-in minus a constant (the two had identical importance). Evaluation tables (`model_*`) are
  written to DuckDB for the app.
- **Consequences:** An interpretable model wins, so reason codes and the coefficients tell the same story.
  The refit model has no held-out score of its own; the validation and backtest numbers stand in for it,
  and the oracle check confirms them on the open intake.

### ADR-020 — Action-queue reason codes follow the model, not intuition
- **Context:** CLAUDE.md's example reason code includes "booked 7 months early". Among bookings alive 72
  days before move-in, early bookers are lower risk (FINDINGS §3). Most agents have more than a day of
  backlog this far out, so an absolute load flag fired on 59% of the queue.
- **Decision:** Reason codes are visa pending/not applied, no deposit, no reply since booking, agent
  overloaded (≥ 1.5x team load) and rent over budget. "Booked N months early" is dropped.
- **Consequences:** The overload flag now marks exactly agents 10 and 13. Codes point agents at what to
  talk about.

### ADR-021 — Executive KPIs compare like with like
- **Context:** CLAUDE.md asks for KPI cards with a delta vs the last comparable intake. The open intake
  (Jan-2027) is 72 days from move-in, so comparing it with a complete intake would always look like a collapse.
- **Decision:** Money cards compare Jan-2027 with Jan-2026 *at the same point in its cycle*: bookings
  made at least 72 days before move-in. Revenue at Risk is compared as a share. The share of commission
  still live at this point that we expect to lose is set against the share Jan-2026 actually lost from the
  same point (`live_commission_loss_share`). Rate cards use the latest intake that has moved in (Sep-2026)
  vs the year before. All of this is in `sql/15_commission_by_intake.sql` and `stayguard.kpis`.
- **Consequences:** Every delta is a fair comparison, and the tooltip on each card says what it compares
  against. The intake filter does not apply to the cards, which are pinned to their intakes, and the page
  says so.

### ADR-022 — App filters applied at each query's grain, and said out loud
- **Context:** The SQL library is unparameterised (one file per business question, tested as-is), but the
  app has global filters.
- **Decision:** KPI cards and the simulator use `metrics.py` with `Filters` (every filter applies). Charts
  filter each query's result on whichever filter columns its grain has. Each "How this number is
  calculated" panel lists the filters applied and those that could not be. Filter values persist across
  pages through session state.
- **Consequences:** No number silently ignores a filter. Some charts (agent leaderboard, budget bands)
  are all-markets by design and say so.

### ADR-023 — What-if simulator: three levers, applied in order, all assumptions shown
- **Context:** CLAUDE.md asks for queue share, save rate, deposit policy and response SLA → projected ENC.
- **Decision:** Levers are applied in sequence so nothing is double-counted:
  1. Deposits: the risk of chased bookings falls to the model's counterfactual `p_cancel_if_deposit`.
  2. Calls: the top share of remaining expected loss × save rate.
  3. SLA: pipeline leads × extra share answered in time × the historical conversion gap × average
     commission × survival.
- **Consequences:** Levers 1 and 3 read causal effects off observational data, and the page says so next to
  the result. A test pins the calls lever to `metrics.saveable_revenue_gbp`.

### ADR-024 — AI client: structured JSON, cached system prompt, refusal fallbacks
- **Context:** The AI layer must return parseable answers, be cheap to run repeatedly, and be testable
  without a key.
- **Decision:**
  - One `LLMClient` interface: `AnthropicClient` in the app, `ScriptedClient` in tests.
  - Every call uses structured outputs (`output_config.format` with a JSON schema) on
    `claude-sonnet-5-5` (CLAUDE.md §2; overridable with `ANTHROPIC_MODEL`) at effort `medium`.
  - The large, stable system prompt (schema context and examples) is cached with `cache_control`.
  - Server-side refusal fallbacks (`fallbacks: "default"`) are enabled.
  - API errors map to friendly messages.
- **Consequences:** No JSON parsing failures by construction. `make test` needs no key. Repeated calls reuse
  the cached prompt prefix.

### ADR-025 — Guardrail blocks are final; self-repair only for execution errors
- **Context:** CLAUDE.md asks for one automatic self-repair retry on SQL errors.
- **Decision:** A query that fails when it runs (wrong column, type error) gets one retry with the error
  passed back. A query rejected by the guardrails (DML, file access, other tables) does not: the model is
  never given a second attempt to get round a safety rule. `fact_booking` stays queryable so the verifier
  can demonstrate the duplicate-rows warning.
- **Consequences:** Injection-style questions fail closed. A blocked question costs one model call.

### ADR-026 — Verification semantics
- **Context:** The badge must mean something to a stakeholder.
- **Decision:**
  - **Badge rule:** any failed check gives ⚠️ Mismatch. Otherwise, the canonical-metric check or the
    independent re-derivation passing gives ✅ Verified. Otherwise ◻️ Unverifiable.
  - **Tolerance:** 0.5% relative for money and rates; whole numbers (counts) must match exactly.
  - **Independence:** the independent query comes from a different prompt and never sees the first SQL.
    The canonical metric is computed by `metrics.py` in pandas.
- **Consequences:** The eval's headline is "wrong but verified" (must be empty), not just accuracy.

### ADR-027 — Live AI eval deferred (no API key for now)
- **Context:** Phase 6's acceptance includes running the 15-question eval against the live model. No
  Anthropic API key is available at the moment (decision taken 2026-11-03).
- **Decision:** Ship the AI layer verified offline only:
  - guardrail tests
  - the eval harness run with a scripted "perfect" model (all pass) and a "careless" model (every trap
    flagged, none verified)
  - the verifier and memo-checker tests

  No demo answers or memo are fabricated: the demo cache and memo cache stay empty until a real run.
- **Consequences:**
  - The app runs fully without a key. Ask the Data says demo answers have not been generated yet, and Home
    shows the rule-based insights.
  - The live-eval acceptance criterion is open.
  - To close it: put a key in `.env`, then run `make ai-eval` and `make ai-memo` (estimated under $1), and
    commit `data/demo_cache.json`, `data/memo_cache.json` and `tests/ai_eval/results/`.

### ADR-028 — MCP server on the 2.x SDK (`MCPServer`), sharing the AI guardrails
- **Context:** CLAUDE.md specifies FastMCP. In the installed MCP Python SDK (2.3), FastMCP has been
  renamed `MCPServer`, and some names changed (snake_case fields such as `read_only_hint`, `is_error`).
- **Decision:**
  - Use `mcp.server.mcpserver.MCPServer`, the same decorator-based design under its 2.x name.
  - Keep the tool logic in `stayguard.mcp_tools`, free of MCP so it is unit-testable;
    `mcp_server/server.py` only registers four tools, all annotated read-only.
  - SQL goes through `ai/guardrails.py`, the same rules as Ask the Data. The verifier's currency and
    duplicate checks come back as warnings.
  - Queries are logged to the audit DB.
  - `STAYGUARD_DB_PATH` lets tests point the server at a temporary database.
- **Consequences:** One set of guardrails for every way an AI touches the data. A pytest test starts the
  real server over stdio and calls it like Claude Code does.
