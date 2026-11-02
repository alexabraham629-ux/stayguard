# StayGuard: Booking Risk Copilot

> **Synthetic data, portfolio project.** Inspired by the business model of student-housing
> marketplaces such as Amber. No real company data, names or brand assets are used.

StayGuard estimates how much booked commission will actually land, ranks which open bookings
booking managers should call today, and lets stakeholders ask the data questions in plain English,
with every AI answer checked against canonical metrics.

*This README is a stub. The portfolio version (findings, screenshots, architecture) lands in Phase 8.*

## Quick start (Windows or macOS)

Prerequisites: [uv](https://docs.astral.sh/uv/) and GNU make.

```bash
make setup   # creates .venv with Python 3.12 and installs dependencies
make data    # generates the synthetic data (~5 s) and builds data/stayguard.duckdb
make test    # runs the test suite (no API key needed)
make app     # launches the Streamlit app
```

Copy `.env.example` to `.env` and add your own `ANTHROPIC_API_KEY` to enable live AI features.
Without a key the app runs in Demo mode.
