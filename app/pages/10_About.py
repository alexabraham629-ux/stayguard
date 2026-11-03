"""About / Method: the problem, who it is for, how it works, and what the data is."""

import streamlit as st

from stayguard.ui.layout import footer, page

page(
    "About StayGuard",
    "A booking-risk copilot for student-housing marketplaces. Portfolio project on synthetic data.",
    "ℹ️",
)

st.info(
    "**All data is synthetic.** Students, agents, universities and bookings are simulated, with "
    "known effects planted so the analysis can be checked against ground truth. The project is "
    "inspired by the business model of student-housing marketplaces; it is not affiliated with "
    "any company and uses no real company data.",
    icon="🧪",
)

st.subheader("The problem")
st.markdown(
    "A marketplace earns commission from property operators when a student's booking turns into "
    "a move-in. Until then the commission is at risk: visa refusals, no place at university, "
    "cooling-off periods and students who find something cheaper. StayGuard answers three "
    "questions:\n\n"
    "1. **Finance:** how much of our booked commission will really land? "
    "(expected net commission)\n"
    "2. **Operations:** which students should booking managers call today? (risk-ranked queue)\n"
    "3. **Strategy:** which cities, countries, intakes and channels are leaking revenue?"
)

st.subheader("Who it is for")
st.table(
    {
        "Persona": [
            "Revenue / Finance lead",
            "Ops head / team lead",
            "City / supply manager",
            "Any stakeholder",
        ],
        "Job to be done": [
            "Tell me what commission will actually land this intake and what is at risk.",
            "Tell my team which students to call today and whether we have capacity.",
            "Which cities and properties are under-converting or over-cancelling?",
            "Answer my ad-hoc question without waiting for an analyst, without a wrong number.",
        ],
        "Start here": [
            "Executive overview, Revenue at risk",
            "Action queue, Agent ops",
            "Market radar, Funnel & cohorts",
            "Ask the data (AI layer)",
        ],
    }
)

st.subheader("How it works")
# Static, trusted HTML written here (never user or model input), rendered by Mermaid (ADR-012).
st.iframe(
    """
    <div class="mermaid" style="font-family: system-ui, sans-serif;">
    flowchart LR
      G["Synthetic data generator<br/>seeded, planted effects"] --> DB[("DuckDB")]
      DB --> SQL["SQL library<br/>17 tested queries"]
      DB --> M["metrics.py<br/>source of truth"]
      DB --> ML["Cancellation model<br/>survival-aware, leakage-guarded"]
      ML -->|scored_bookings| DB
      SQL --> APP["Streamlit app"]
      M --> APP
      M -. reconciles .- SQL
      APP --> AI["AI layer (next phase)<br/>NL to SQL + verifier"]
      AI -. checks against .-> M
    </div>
    <script type="module">
      import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.esm.min.mjs";
      mermaid.initialize({ startOnLoad: true, theme: "neutral" });
    </script>
    """,
    height=240,
)
st.markdown(
    "- **Every number is traceable.** Each chart's *How this number is calculated* panel names the "
    "SQL file and shows the data behind it.\n"
    "- **Two independent implementations.** The SQL library and `metrics.py` (pandas) compute the "
    "same metrics separately; tests fail if they disagree.\n"
    "- **Honest model evaluation.** Time-based validation, a leakage guard, and a check "
    "against the "
    "hidden true outcomes that only synthetic data allows.\n"
    "- **Assumptions in one place.** Commission rates, FX, save rate and SLA live in "
    "`config/assumptions.yaml` and are labelled as assumptions wherever they appear."
)

st.subheader("Limitations")
st.markdown(
    "Fixed FX rates; stylised rents and commission rates; no supply constraint; what-if levers "
    "read causal effects off observational data. See `docs/DATA_GENERATION.md` and "
    "`docs/FINDINGS.md` in the repository (link added at deployment)."
)
footer()
