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
