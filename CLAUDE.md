# CLAUDE.md — StayGuard: Booking Risk Copilot for Student-Housing Marketplaces

> This file is the single source of truth for this project. Read it fully before writing any code.
> Re-read the relevant section at the start of every phase. When something here conflicts with
> your instinct, follow this file; if it seems wrong, stop and ask me rather than silently deviating.

---

## 0. Why this project exists (context you must understand)

I am an MBA (Business Analytics) student building a portfolio project for an **AI Data Analyst
Intern** role at a student-housing booking marketplace (Amber, amberstudent.com — think
"booking.com for student housing"). The hiring team explicitly wants someone who:

- writes and optimises **SQL** (joins, aggregations, **window functions**),
- builds **dashboards** (Power BI / Tableau),
- uses **AI chatbots and AI coding tools** (Claude, Claude Code) as a core part of their workflow,
- **checks every AI-produced number against source data before it reaches a stakeholder**,
- turns patterns into **clear business recommendations**,
- **documents prompts, workflows and automations** so a team can reuse them,
- bonus: **Python (pandas)**, **APIs / MCP**, product-analytics thinking.

The application also asks: *"one thing the AI got wrong that you had to fix."* So this project must
genuinely log AI mistakes we catch during the build (see §11).

The product must look like a **product manager and a senior analyst spent weeks on it**: a clear
problem statement, personas, metric definitions, decisions log, tested SQL, a verified AI layer,
and a polished UI. Quality over feature count. Every number on screen must be traceable to a query.

### The business problem
A student-housing marketplace earns **commission from property operators on confirmed bookings**.
But a booking is not revenue until it survives the cancellation window. UK/AU/IE properties
commonly offer "No Visa, No Pay", "No Place, No Pay" and 7-day cooling-off cancellations, and the
UK market softened in 2025-26 (falling international postgraduate demand, students booking later).
Commission is effectively "at risk" until move-in.

**StayGuard answers three questions:**
1. **Finance:** How much of our booked commission is really going to land? (expected net commission, revenue at risk)
2. **Operations:** Which bookings should booking managers call *today* to save the most revenue? (risk-ranked action queue, agent capacity)
3. **Business/Strategy:** Which cities, source countries, intakes and channels are leaking revenue, and what should we do? (funnel, cohorts, recommendations)

…and lets any stakeholder **ask the data in plain English**, with every AI answer **automatically verified**.

### Branding rule
Do **not** use Amber's name, logo, colours or brand assets inside the app UI. The app is
"StayGuard". The README may say it is *inspired by the business model of student-housing
marketplaces such as Amber*. All data is **synthetic** and must be labelled as such everywhere.

---

## 1. Personas & jobs-to-be-done

| Persona | Job to be done | Primary page |
|---|---|---|
| **Revenue / Finance Lead** | "Tell me what commission will actually land this intake and what is at risk." | Executive Overview, Revenue at Risk |
| **Ops Head / Booking-Manager Team Lead** | "Tell my team which students to call today and whether we have capacity." | Action Queue, Agent Ops |
| **City / Supply Manager** | "Which cities and properties are under-converting or over-cancelling?" | Market Radar, Funnel |
| **Any stakeholder** | "Answer my ad-hoc question without waiting for an analyst — but don't give me a wrong number." | Ask the Data |

### North-star & success metrics (write these into `docs/PRD.md`)
- **North star:** Expected Net Commission (ENC) for the upcoming intake.
- Supporting: booking→move-in survival rate, cancellation rate (by reason), lead→booking conversion,
  median first-response time, revenue at risk, % of AI answers auto-verified.

---

## 2. Tech stack (use exactly this unless you ask first)

- **Python 3.11+**, dependency management with `uv` (fallback: `pip` + `requirements.txt`; keep both in sync).
- **DuckDB** as the analytical database (single file `data/stayguard.duckdb`). SQL dialect = DuckDB.
- **pandas**, **numpy**, **Faker** (data generation), **scikit-learn** (models), **plotly** (charts).
- **Streamlit** (multi-page app) for the UI.
- **Anthropic Python SDK** for the AI features. Model read from env var `ANTHROPIC_MODEL`,
  default `claude-sonnet-5-5`. API key from `ANTHROPIC_API_KEY` (never hard-code; use `.env` + `python-dotenv`; ship `.env.example`).
- **sqlglot** for parsing/validating AI-generated SQL.
- **mcp** Python SDK (FastMCP) for a read-only MCP server over the database.
- **pytest**, **ruff** (lint + format). Type hints everywhere.
- Deployment target: **Streamlit Community Cloud** (free). Must run with `streamlit run app/Home.py`.

---

## 3. Repository structure (create exactly this)

```
stayguard/
├── CLAUDE.md
├── README.md                      # portfolio-grade, see §12
├── pyproject.toml / requirements.txt
├── .env.example
├── .mcp.json                      # registers our MCP server for Claude Code
├── config/
│   └── assumptions.yaml           # ALL business assumptions (commission %, FX, save-rate…) in one place
├── data/
│   ├── raw/                       # generated CSVs (gitignored except a small sample)
│   ├── stayguard.duckdb           # built DB (gitignored; rebuilt by `make data`)
│   └── exports/                   # star-schema CSV/Parquet for Power BI/Tableau
├── src/stayguard/
│   ├── generate/                  # synthetic data generator (seeded, reproducible)
│   ├── db.py                      # connection helpers (read-only connection for app & AI)
│   ├── metrics.py                 # canonical metric functions = the "source of truth"
│   ├── sql_runner.py              # loads & runs named queries from /sql
│   ├── quality/                   # data-quality checks
│   ├── model/                     # cancellation-risk features, training, scoring, evaluation
│   ├── ai/
│   │   ├── nl2sql.py              # NL → SQL with guardrails
│   │   ├── verifier.py            # independent verification of AI answers
│   │   ├── memo.py                # grounded insight memo generator + number checker
│   │   ├── prompts/               # every prompt as a versioned .md file
│   │   └── audit.py               # logs every AI call to the ai_audit table
│   └── sim/                       # what-if simulator
├── sql/                           # the SQL library (see §6), one file per business question
├── app/
│   ├── Home.py                    # Executive Overview
│   └── pages/                     # see §8
├── mcp_server/server.py
├── tests/
├── notebooks/01_eda.ipynb         # short, clean EDA that tells a story
├── dashboards/
│   ├── powerbi_spec.md            # star schema, DAX measures, page layouts
│   └── screenshots/
├── docs/
│   ├── PRD.md
│   ├── METRICS.md                 # metric dictionary (definition, formula, SQL file, owner)
│   ├── DATA_GENERATION.md         # how data is simulated + the planted ground-truth effects
│   ├── DECISIONS.md               # ADR-style decisions log
│   ├── PROMPTS.md                 # prompt library: purpose, version, inputs, known failure modes
│   ├── AI_LOG.md                  # REAL AI mistakes caught during the build (see §11)
│   └── FINDINGS.md                # the business insights & recommendations
└── Makefile                       # make setup | data | test | app | export | lint
```

---

## 4. Synthetic data specification

Generator must be **deterministic** (global seed in `assumptions.yaml`), produce ~**60,000 leads**
and ~**18,000 bookings**, and finish in < 60 seconds. Snapshot date ("today" inside the data):
**2026-10-31**. Intakes covered: **Sep-2024, Jan-2025, Sep-2025, Jan-2026, Sep-2026, Jan-2027**
(Jan-2027 bookings are still open → these are what we score and act on).

### Tables (DuckDB, snake_case, explicit types, PKs/FKs documented)

- `dim_city` — city_id, city, country (UK/AU/IE), currency, market_tier, fx_to_gbp
  - Cities: London, Manchester, Birmingham, Nottingham, Leeds, Glasgow, Coventry, Sheffield, Sydney, Melbourne, Brisbane, Dublin.
- `dim_university` — university_id, name (**fictional** names only, e.g. "Northbridge University"), city_id, intl_share
- `dim_property` — property_id, city_id, operator_type (PBSA chain / independent PBSA / HMO), room_type (ensuite/studio/shared), weekly_rent_local, has_no_visa_no_pay (bool), cooling_off_days, distance_km_to_university, rating
- `dim_agent` — agent_id, agent_name (Faker), team, languages, hire_date, max_daily_capacity
- `dim_student` — student_id, source_country (India, China, Nigeria, Pakistan, Nepal, UK, Vietnam, Saudi Arabia, USA, Other), level (UG/PG), university_id, budget_weekly_gbp, has_guarantor
- `fact_lead` — lead_id, student_id, created_at, channel (organic, paid_search, referral, ambassador, partner_consultancy, loan_partner), intake, city_id, first_response_minutes, agent_id, status (new/contacted/shortlisted/booked/lost), lost_reason
- `fact_booking` — booking_id, lead_id, student_id, property_id, agent_id, booked_at, intake, tenancy_weeks, weekly_rent_local, currency, gbv_local, commission_rate, commission_local, deposit_paid (bool), visa_status_at_booking (not_applied/pending/granted/not_required), days_booked_before_intake, status (confirmed/cancelled/moved_in/open)
- `fact_cancellation` — booking_id, cancelled_at, reason (visa_refused, no_place, cooling_off, found_cheaper, duplicate_booking, changed_plans, other), refund_amount_local, days_after_booking
- `fact_interaction` — interaction_id, booking_id or lead_id, agent_id, ts, type (call/whatsapp/email), outcome
- `ai_audit` — (created by app) every AI request: ts, feature, prompt_version, question, generated_sql, verification_status, latency_ms, tokens

### Planted ground-truth effects (the analysis must later RE-DISCOVER these)
Encode these with noise so they are discoverable but not trivial. Document them in
`docs/DATA_GENERATION.md` under a "ground truth" heading, and write a test that checks the
model/analysis recovers the direction of each effect.

1. `visa_status_at_booking = pending` or `not_applied` → much higher cancellation (esp. reason `visa_refused`), stronger for certain source countries (make Nigeria and Pakistan visa-refusal rates higher, India medium, China/USA low).
2. `deposit_paid = false` → higher cancellation.
3. Bookings made **> 180 days before intake** cancel more (`found_cheaper`, `duplicate_booking`); bookings **< 30 days** before intake cancel least.
4. `first_response_minutes` > 240 → lower lead→booking conversion.
5. `ambassador` and `partner_consultancy` channels convert better; `paid_search` converts worst.
6. PG students in 2025-26 show a demand drop vs 2024-25 (softening market), stronger in non-London UK cities.
7. Two agents are over capacity (too many open bookings) and their bookings cancel more — an operations insight.
8. Strong seasonality: lead spikes Feb–Jul for Sep intake, Sep–Nov for Jan intake.

### Planted data-quality issues (so validation has something real to catch)
- ~0.5% duplicate bookings (same student, same property, within 48h).
- Some null `first_response_minutes`.
- Mixed currencies (GBP/AUD/EUR) — any revenue total must convert via `fx_to_gbp`. **Summing local currency across countries is a bug we must guard against.**
- A handful of `cancelled_at` timestamps before `booked_at` (to be flagged, not silently used).

---

## 5. Metric dictionary (canonical; implement in `metrics.py` AND document in `docs/METRICS.md`)

All money reported in **GBP** (convert with `fx_to_gbp`). Assumptions live in `config/assumptions.yaml`.

| Metric | Definition |
|---|---|
| GBV | weekly_rent × tenancy_weeks (converted to GBP) |
| Booked Commission | GBV × commission_rate (assumption: 8–14% by operator_type; **label as assumption**) |
| Realised Commission | commission on bookings with status `moved_in` |
| Cancellation Rate | cancelled bookings ÷ all bookings (deduplicated), for closed intakes |
| Survival Rate | 1 − cancellation rate |
| p_cancel | model-predicted probability an open booking cancels |
| **Expected Net Commission (ENC)** | Σ commission × (1 − p_cancel) over open bookings |
| **Revenue at Risk** | Σ commission × p_cancel over open bookings |
| Lead→Booking Conversion | booked leads ÷ leads, by cohort (lead created month) |
| Median First Response | median of first_response_minutes (nulls excluded and counted separately) |
| Agent Load | open bookings per agent ÷ max_daily_capacity |
| Saveable Revenue | Revenue at Risk in the top-N queue × assumed intervention save-rate (assumption) |

`metrics.py` is the **source of truth**. The AI verifier compares against it.

---

## 6. SQL library (`/sql`) — this is a showcase; make it excellent

One file per business question, numbered. Each file begins with a header block:

```sql
-- name: 05_rolling_cancellation_rate
-- business_question: Is our cancellation rate trending up week over week?
-- stakeholder: Revenue Lead
-- techniques: CTE, window function (AVG OVER ROWS BETWEEN), date_trunc
-- grain: one row per city per week
-- validated_by: tests/test_sql.py::test_rolling_cancellation_matches_metrics
```

Required queries (all must run on DuckDB and have a pytest that checks them):

1. `01_funnel_by_city_intake` — lead → contacted → shortlisted → booked → moved-in, with step conversion %.
2. `02_weekly_booking_velocity` — weekly bookings with `LAG` for WoW change and same-week-last-year comparison.
3. `03_cohort_cancellation_curve` — cumulative cancellation % by days-since-booking buckets per intake cohort.
4. `04_cancellation_reasons_pareto` — reasons ranked with running share (`SUM() OVER (ORDER BY …)`) → 80/20.
5. `05_rolling_cancellation_rate` — 4-week rolling average with explicit window frame.
6. `06_agent_leaderboard` — `RANK()`, `NTILE(4)` on conversion, response time, cancellation rate, load.
7. `07_revenue_at_risk_by_city` — joins scored bookings → ENC, Revenue at Risk, share of total.
8. `08_response_time_vs_conversion` — `QUANTILE_CONT` buckets of response time vs conversion.
9. `09_source_country_visa_risk` — cancellation by source_country × visa_status.
10. `10_duplicate_booking_detection` — self-join / `ROW_NUMBER()` to flag duplicates.
11. `11_yoy_pg_demand_by_city` — PG bookings YoY by city (softening-market evidence).
12. `12_channel_unit_economics` — conversion, avg commission, cancellation by channel.
13. `13_action_queue` — today's prioritised call list: open bookings ranked by commission × p_cancel, assigned to agents within capacity.
14. `14_data_quality_report` — counts of each planted issue.

Rules: CTEs over nested subqueries; no `SELECT *` in final selects; comment non-obvious logic;
always convert currency before aggregating money; filter duplicates via a shared `clean_bookings` view.
Create the views `v_clean_bookings` and `v_bookings_gbp` once and reuse them.

---

## 7. Cancellation risk model (`src/stayguard/model/`)

- **Target:** booking cancelled (closed intakes only).
- **Time-based split:** train on Sep-2024 → Jan-2026 intakes, validate on Sep-2026. Never random-split across time.
- **Leakage guard:** features must be knowable at booking time. Explicitly exclude `cancelled_at`, `refund_amount`, `status`, `reason`, post-booking interactions after the scoring date. Write a test that fails if a leaky column enters the feature list.
- **Models:** Logistic Regression baseline (interpretable) + `HistGradientBoostingClassifier`. Pick by PR-AUC on validation.
- **Report:** ROC-AUC, PR-AUC, Brier score, **calibration plot**, lift/gains at top decile, permutation importance, and the **business metric**: revenue saved if the team works the top 20% of the queue with save-rate from `assumptions.yaml`.
- **Recovery check:** the model's top features should align with planted effects (§4). Record outcome in `docs/FINDINGS.md`.
- Score Jan-2027 open bookings → write `scored_bookings` table back to DuckDB.

---

## 8. Streamlit app pages

Visual bar: clean, modern, consistent. Custom theme in `.streamlit/config.toml`, a single accent
colour, generous whitespace, KPI cards with delta vs last comparable intake, every chart titled as an
**insight** ("London carries 41% of revenue at risk"), not a label ("Revenue by city").
Global sidebar filters: country, city, intake, channel. A persistent footer: "Synthetic data — portfolio project".
Every page has an expander **"How this number is calculated"** showing the SQL file used.

1. **Home — Executive Overview:** KPI cards (Booked Commission, ENC, Revenue at Risk, Cancellation Rate, Conversion), ENC trend, top 3 auto-generated insights (from §9.3, verified).
2. **Funnel & Cohorts:** funnel chart, cohort cancellation curves, seasonality heatmap.
3. **Revenue at Risk:** risk distribution, revenue at risk by city/source country/visa status, model performance tab (calibration, lift, importance) written for non-technical readers.
4. **Action Queue (Ops):** today's call list (from `13_action_queue`) with reason codes ("visa pending + no deposit + booked 7 months early"), agent assignment respecting capacity, CSV download.
5. **Agent Ops:** leaderboard, load vs cancellation scatter, response-time impact.
6. **Market Radar:** YoY PG demand by city, channel unit economics, price band vs conversion.
7. **What-If Simulator:** sliders — % of queue worked, save-rate, deposit-required policy, response-time SLA → projected ENC change, with all assumptions shown. (Finance × Ops crossover.)
8. **Ask the Data (AI):** see §9.1–9.2. This is the hero feature.
9. **AI Audit & Prompt Library:** table of `ai_audit` (verification pass rate, latency), and rendered `docs/PROMPTS.md`.
10. **About / Method:** problem, personas, data disclaimer, architecture diagram (Mermaid), link to repo.

Performance: cache queries with `st.cache_data`; app must load in < 3 s locally.

---

## 9. AI features — the "uses AI but checks every number" story

### 9.1 NL → SQL (`ai/nl2sql.py`)
- Prompt includes: schema (tables, columns, types, descriptions), metric dictionary, 6–8 few-shot
  question→SQL examples, DuckDB dialect notes, and the rule *"always convert money to GBP; use v_clean_bookings"*.
- Model returns **JSON**: `{sql, assumptions, explanation}`.
- **Guardrails (all enforced in code, not just prompt):** parse with `sqlglot` (dialect duckdb);
  allow only `SELECT`/`WITH`; table whitelist; auto-append `LIMIT 1000`; execute on a
  **read-only** DuckDB connection with a timeout; on SQL error, one automatic self-repair retry
  passing the error back; otherwise show a friendly failure.

### 9.2 Verifier (`ai/verifier.py`) — the hero
For every AI answer, run independent checks and show a badge: **✅ Verified / ⚠️ Mismatch / ◻️ Unverifiable**.
1. **Canonical metric match:** if the question maps to a metric in `metrics.py`, compute it deterministically and compare (tolerance 0.5%).
2. **Independent re-derivation:** ask the model, in a *separate* call with a different prompt, for an alternative SQL approach to the same question; compare results.
3. **Sanity checks:** row counts vs base tables, currency mixing detector (money columns aggregated without FX join → flag), date-range check vs filters, duplicates check.
Show the user the SQL, the check results, and a plain-English explanation. Log everything to `ai_audit`.

### 9.3 Grounded insight memo (`ai/memo.py`)
- Compute a metrics JSON from `metrics.py` + SQL library. Model writes a weekly memo (headline,
  3 insights, 3 recommendations with owner and expected impact) **only from that JSON**.
- **Number checker:** regex-extract every number in the memo; each must match a value in the JSON
  (with rounding tolerance). Unmatched numbers → regenerate once, then highlight in red. Display pass/fail.

### 9.4 Demo mode
If no `ANTHROPIC_API_KEY` is present, the app must still work: AI pages use a cached set of
pre-recorded question/answer/verification examples (stored in `data/demo_cache.json`) with a clear
"Demo mode" banner. The deployed public demo must never expose my key; add a simple per-session
rate limit when a key is present.

### 9.5 MCP server (`mcp_server/server.py`)
FastMCP server exposing `list_tables`, `describe_table(name)`, `run_readonly_query(sql)` (same
guardrails as 9.1) and `get_metric(name, filters)`. Register it in `.mcp.json` so Claude Code
(and Claude Desktop) can query the database directly. Document setup in README.

---

## 10. Data quality & testing

- `quality/` checks: uniqueness of PKs, FK integrity, null rates, negative amounts, timestamp order,
  duplicate bookings, currency coverage. Output `14_data_quality_report` + a page section.
- `tests/`: generator determinism, every SQL file runs, SQL results reconcile with `metrics.py`,
  leakage test, planted-effect recovery tests, NL→SQL guardrail tests (must reject `DROP`, `INSERT`,
  non-whitelisted tables, multiple statements), memo number-checker tests (mock LLM).
- `make test` must pass with no API key (mock the LLM client).
- `ruff check` clean.

---

## 11. AI mistake log (`docs/AI_LOG.md`) — be honest

Whenever **you (Claude Code)** produce something wrong that a test, a reconciliation check, or I
catch — e.g. a wrong window frame, summing mixed currencies, a leaky feature, an off-by-one date
filter, a hallucinated column — append an entry:

```
### YYYY-MM-DD — <short title>
- What the AI produced:
- How it was caught (test / reconciliation / manual review):
- Fix:
- Lesson / guardrail added:
```

**Never invent entries.** Only log genuine issues that occurred. If a phase had none, write nothing.
Also log AI failures observed in the app's own NL→SQL testing (from `ai_audit`).

---

## 12. Documentation deliverables

- **README.md** (portfolio-grade): one-line pitch, 30-second problem statement, GIF/screenshots,
  key findings with numbers, architecture diagram (Mermaid), how AI is used *and verified*, tech
  stack, run instructions, MCP setup, limitations & synthetic-data disclaimer, "what I'd do next".
- **docs/PRD.md:** problem, personas, JTBD, scope / non-goals, success metrics, risks.
- **docs/METRICS.md, DATA_GENERATION.md, DECISIONS.md, PROMPTS.md, AI_LOG.md, FINDINGS.md** as described.
- **dashboards/powerbi_spec.md:** star schema from `data/exports/`, relationships, 10+ DAX measures
  (ENC, Revenue at Risk, Cancellation Rate, YoY %, rolling 4-week cancellation, etc.), and 3 page
  layouts, so I can build the Power BI dashboard myself in ~2 hours.
- `make export` writes the star-schema tables as CSV and Parquet for Power BI/Tableau.

---

## 13. Build phases (work ONE phase at a time)

After each phase: run tests, run ruff, update docs touched, make a git commit with a clear message,
then **stop and give me a short summary** (what was built, how to see it, any AI_LOG entries,
open questions). Do not start the next phase until I say "next".

| Phase | Scope | Acceptance criteria |
|---|---|---|
| **0. Plan** | Read this file. Propose a plan, flag risks/ambiguities, confirm stack. | I approve the plan. No code yet beyond scaffolding. |
| **1. Scaffold** | Repo structure, pyproject, Makefile, config, ruff, pytest, `.env.example`, git init. | `make setup && make test` runs. |
| **2. Data** | Generator, DuckDB build, views, quality checks, DATA_GENERATION.md. | Determinism test passes; planted issues show in quality report. |
| **3. SQL library + metrics** | All 14 queries, `metrics.py`, METRICS.md, reconciliation tests. | Every SQL test passes; SQL == metrics within tolerance. |
| **4. Model** | Features, leakage test, training, evaluation, scoring, FINDINGS draft. | Leakage test passes; planted effects recovered; scored table written. |
| **5. App (non-AI)** | Pages 1–7 and 10, theme, filters, "how calculated" expanders. | App loads < 3 s; every KPI traced to a SQL file. |
| **6. AI layer** | NL→SQL, guardrails, verifier, memo + number checker, audit, demo mode, pages 8–9. | Guardrail tests pass; 15-question eval set (in `tests/ai_eval/`) run and results logged. |
| **7. MCP** | MCP server, `.mcp.json`, README section. | I can query the DB from Claude Code via MCP. |
| **8. Polish & ship** | README, screenshots, Power BI spec, exports, deploy notes, final AI_LOG & FINDINGS review. | Fresh clone → `make setup data app` works; deploy checklist done. |

---

## 14. Working agreements for Claude Code

- Prefer clear, boring, well-named code over clever code. Small functions, docstrings, type hints.
- Never hard-code numbers that belong in `config/assumptions.yaml`.
- When you state a number to me in a summary, it must come from running code in this session.
- If a test fails, fix the cause; do not weaken the test without telling me why.
- Keep business language in the UI; keep technical language in docs and expanders.
- Ask me before adding any dependency not listed in §2.
- I am learning: when you finish a phase, explain in 3–5 bullets the key SQL/Python techniques used
  so I can explain them confidently in an interview.
