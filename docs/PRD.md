# PRD — StayGuard: booking-risk copilot

> Synthetic data, portfolio project. Inspired by the business model of student-housing marketplaces;
> not affiliated with any company.

## 1. Problem

A student-housing marketplace earns commission from property operators on bookings, but a booking
only becomes revenue when the student moves in. Until then commission is at risk:
- visa refusals and "No Visa, No Pay" policies
- no university place ("No Place, No Pay")
- 7–14-day cooling-off periods
- students who find somewhere cheaper

In 2025–26 the UK market softened: fewer international postgraduates, booking later. Finance plans
on booked commission and is surprised by what lands. Booking managers call students in no particular
order, and nobody can answer an ad-hoc question without waiting for an analyst.

## 2. Users and jobs to be done

| Persona | Job to be done | Primary page |
|---|---|---|
| Revenue / Finance lead | Tell me what commission will actually land this intake and what is at risk. | Executive overview, Revenue at risk |
| Ops head / booking-manager team lead | Tell my team which students to call today and whether we have capacity. | Action queue, Agent ops |
| City / supply manager | Which cities and properties are under-converting or over-cancelling? | Market radar, Funnel & cohorts |
| Any stakeholder | Answer my ad-hoc question without waiting for an analyst, and without a wrong number. | Ask the data (Phase 6) |

## 3. Scope

**In scope (v1)**
- Synthetic, reproducible marketplace data with planted ground truth.
- SQL library of business questions and a canonical metric layer. The two are reconciled by tests.
- Survival-aware cancellation-risk model scoring the open intake.
- Streamlit app:
  - executive KPIs
  - funnel and cohorts
  - revenue at risk and model quality
  - action queue
  - agent ops
  - market radar
  - what-if simulator
  - About/method
- AI layer (Phase 6): plain-English questions to SQL, with independent verification of every answer
  and an audit log.
- MCP server (Phase 7) so Claude can query the database directly.

**Non-goals**
- Real company data, real student data or any production integration.
- Causal estimates of policy effects: the What-If levers are labelled projections from assumptions.
- Pricing optimisation, supply/inventory management and payments.
- Per-user authentication or write access from the app (the app is read-only).

## 4. Success metrics

- **North star:** Expected Net Commission (ENC) for the open intake = Σ commission × (1 − p_cancel).
  Its definition is in `docs/METRICS.md`.
- **Supporting metrics:**
  - booking → move-in survival rate
  - cancellation rate, by reason
  - lead → booking conversion
  - median first-response time
  - revenue at risk
  - % of AI answers auto-verified (Phase 6)
- **Product quality bars:**
  - every number on screen traces to a SQL file
  - SQL and `metrics.py` agree in tests
  - every page loads in under 3 s once the server is warm

## 5. Requirements that shaped the design

- **Comparisons are like-for-like:** the open intake is compared with the same intake a year earlier at
  the same point in its cycle (ADR-021).
- **Every page shares the same filters** (country, city, intake, channel). Each "How this number is
  calculated" panel says which filters applied and which could not, given the query's grain (ADR-022).
- **The action queue respects agent capacity** and explains each call with reason codes that follow the
  model (ADR-020).
- **Assumptions are visible** wherever they drive a number: commission rates, FX, save rate, SLA and the
  what-if levers.

## 6. Risks and mitigations

| Risk | Mitigation |
|---|---|
| A wrong number reaches a stakeholder | Two independent implementations (SQL and pandas) reconciled in tests; the Phase 6 verifier on every AI answer |
| Model leakage makes the risk score look better than it is | As-of features, a leakage guard and test, a leakage demonstration, time-based validation |
| Open-intake comparisons mislead (a half-finished intake looks like a collapse) | Like-for-like "same point" comparisons throughout |
| Stakeholders read projections as forecasts | What-if page shows every assumption and its source; labels say "projection" |
| Summing mixed currencies | All money converted in `v_bookings_gbp`; a test fails on naive local sums |
| Brand confusion | No marketplace name, logo or colours in the app; a test scans generated data for the name |
