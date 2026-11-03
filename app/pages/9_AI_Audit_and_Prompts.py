"""AI Audit & Prompt Library: every AI call, how often answers verify, and the prompts."""

import plotly.graph_objects as go
import streamlit as st

from stayguard.ai.audit import AuditLog
from stayguard.ai.eval import RESULTS_DIR
from stayguard.ai.prompts import list_prompts
from stayguard.config import PROJECT_ROOT
from stayguard.ui.layout import chart, footer, page
from stayguard.ui.theme import ACCENT, CRITICAL, NEUTRAL, SURFACE

page(
    "AI audit & prompt library",
    "Every AI request is logged with its SQL, verification result, latency and tokens.",
    "🧾",
)
audit_tab, eval_tab, prompts_tab = st.tabs(["Audit log", "Evaluation", "Prompt library"])

with audit_tab:
    log = AuditLog().read()
    if log.empty:
        st.info(
            "No AI requests have been logged yet. They appear here after `make ai-eval` or live "
            "questions."
        )
    else:
        answered = log.loc[~log["verification_status"].isin(["blocked", "error", ""])]
        verified_share = (
            (answered["verification_status"] == "verified").mean() if len(answered) else 0
        )
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("AI requests", f"{len(log):,}", border=True)
        c2.metric(
            "Answers auto-verified",
            f"{verified_share:.0%}",
            border=True,
            help="Verified / answered requests (blocked and failed requests excluded).",
        )
        c3.metric(
            "Mismatches caught", int((log["verification_status"] == "mismatch").sum()), border=True
        )
        c4.metric(
            "Blocked by guardrails",
            int((log["verification_status"] == "blocked").sum()),
            border=True,
        )

        counts = log["verification_status"].replace("", "error").value_counts()
        st.subheader(f"{verified_share:.0%} of answered questions passed independent verification")
        colors = {"verified": ACCENT, "mismatch": CRITICAL}
        fig = go.Figure(
            go.Bar(
                x=counts.index,
                y=counts.to_numpy(),
                marker=dict(
                    color=[colors.get(s, NEUTRAL) for s in counts.index],
                    line=dict(color=SURFACE, width=2),
                ),
                hovertemplate="%{x}: %{y}<extra></extra>",
            )
        )
        chart(fig, 260)
        st.dataframe(
            log[
                [
                    "ts",
                    "feature",
                    "question",
                    "verification_status",
                    "latency_ms",
                    "input_tokens",
                    "output_tokens",
                    "prompt_version",
                    "model",
                    "error",
                ]
            ].head(200),
            hide_index=True,
            width="stretch",
        )

with eval_tab:
    latest = RESULTS_DIR / "latest.md"
    if latest.exists():
        st.markdown(latest.read_text(encoding="utf-8"))
    else:
        st.info("The 15-question evaluation has not been run yet (`make ai-eval`).")

with prompts_tab:
    doc = PROJECT_ROOT / "docs" / "PROMPTS.md"
    if doc.exists():
        st.markdown(doc.read_text(encoding="utf-8"))
    st.subheader("Prompt files")
    for prompt in list_prompts():
        with st.expander(f"{prompt.version} · {prompt.meta.get('purpose', '')}"):
            st.code(prompt.body, language="markdown")
footer()
