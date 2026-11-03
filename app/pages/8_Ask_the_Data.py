"""Ask the Data: plain-English question -> SQL -> answer, every answer independently verified."""

import streamlit as st

from stayguard.ai.audit import AuditLog, AuditRecord
from stayguard.ai.client import AIError, AnthropicClient, has_api_key
from stayguard.ai.demo import entry_from, load_demo_cache
from stayguard.ai.nl2sql import answer_question
from stayguard.ai.verifier import checks_as_dicts, verify
from stayguard.ui import data
from stayguard.ui.ai_render import render_entry
from stayguard.ui.layout import footer, page

page(
    "Ask the data",
    "Ask a question in plain English. The AI writes the SQL; independent checks verify the number "
    "before you see it.",
    "💬",
)
st.caption(
    "Answers cover all markets: the sidebar filters do not apply here; say it in the question."
)
EXAMPLES = [
    "What was the cancellation rate for the Sep-2026 intake?",
    "How much commission do we expect to land from Jan-2027?",
    "Which channels convert leads into bookings best?",
    "Total gross booking value across all markets for Sep-2025",
]

if not has_api_key():
    st.info(
        "**Demo mode.** No API key is configured, so you are browsing pre-recorded answers. Each "
        "one "
        "is a genuine model answer from the evaluation run, shown with its real verification.",
        icon="🎞️",
    )
    entries = load_demo_cache()
    if not entries:
        st.warning("Demo answers have not been generated yet. Run `make ai-eval` with an API key.")
        footer()
        st.stop()
    choice = st.selectbox("Pick a question", [e["question"] for e in entries])
    st.subheader(choice)
    render_entry(next(e for e in entries if e["question"] == choice))
    footer()
    st.stop()

# --- Live mode ------------------------------------------------------------------------------------
limit = int(data.assumptions()["ai"]["session_rate_limit"])
used = st.session_state.setdefault("ai_requests", 0)
st.caption(f"{limit - used} of {limit} questions left in this session.")

cols = st.columns(len(EXAMPLES))
for col, example in zip(cols, EXAMPLES, strict=True):
    if col.button(example, width="stretch"):
        st.session_state["ai_question"] = example
with st.form("ask"):
    question = st.text_area("Your question", key="ai_question", height=80)
    submitted = st.form_submit_button("Ask", type="primary")

if submitted and question.strip():
    if used >= limit:
        st.warning(
            "You have reached this session's question limit. Reload the app to start a new session."
        )
    else:
        st.session_state["ai_requests"] = used + 1
        con = data.connection().cursor()
        try:
            client = AnthropicClient()
            with st.status("Writing SQL, running it, then checking the answer…", expanded=False):
                answer = answer_question(question, con, client)
                verification = (
                    verify(answer, con, client, data.metric_data()) if answer.ok else None
                )
        except AIError as e:
            st.error(str(e))
            st.stop()
        finally:
            con.close()
        entry = entry_from(answer, verification)
        st.session_state["ai_last"] = entry
        AuditLog().log(
            AuditRecord(
                feature="nl2sql",
                question=question,
                prompt_version=answer.prompt_version,
                model=answer.model,
                generated_sql=answer.sql,
                verification_status=entry["verification_status"] or "error",
                checks=checks_as_dicts(verification.checks) if verification else [],
                latency_ms=answer.latency_ms,
                input_tokens=answer.input_tokens,
                output_tokens=answer.output_tokens,
                error=answer.error,
                session_id=str(id(st.session_state)),
            )
        )

if "ai_last" in st.session_state:
    st.subheader(st.session_state["ai_last"]["question"])
    render_entry(st.session_state["ai_last"])
footer()
