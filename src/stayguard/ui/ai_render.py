"""Rendering for AI answers and the memo, shared by live and demo mode so they look identical."""

from __future__ import annotations

import html
import re
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from stayguard.ui.layout import chart
from stayguard.ui.theme import ACCENT, SURFACE

STATUS_ICON = {"pass": "✅", "fail": "❌", "warn": "⚠️", "skipped": "◻️"}
BADGE = {
    "verified": ("success", "✅ Verified: independent checks agree with this answer."),
    "mismatch": (
        "warning",
        "⚠️ Mismatch: at least one independent check disagrees. Do not quote this number yet.",
    ),
    "unverifiable": ("info", "◻️ Unverifiable: no independent check applied. Treat as a draft."),
}


def render_entry(entry: dict[str, Any]) -> None:
    """One question → answer → evidence, from a demo-cache-style dict."""
    if entry.get("error"):
        if str(entry["error"]).startswith("Blocked"):
            st.error(f"🛡️ {entry['error']}. Nothing was run.", icon=None)
        else:
            st.error(f"Could not answer: {entry['error']}")
        _technical(entry)
        return

    kind, text = BADGE.get(entry.get("verification_status", ""), ("info", "Not verified."))
    getattr(st, kind)(text)
    if entry.get("explanation"):
        st.markdown(entry["explanation"])
    if entry.get("assumptions"):
        st.caption("Assumptions: " + " · ".join(entry["assumptions"]))

    rows = pd.DataFrame(entry.get("rows") or [])
    _result(rows, entry.get("answer_column", ""))

    st.markdown("**How this answer was checked**")
    checks = pd.DataFrame(entry.get("checks") or [])
    if not checks.empty:
        checks.insert(0, "", checks["status"].map(STATUS_ICON))
        st.dataframe(
            checks[["", "name", "detail"]].rename(columns={"name": "Check", "detail": "Result"}),
            hide_index=True,
            width="stretch",
        )
    _technical(entry)


def _result(rows: pd.DataFrame, answer_column: str) -> None:
    if rows.empty:
        st.info("The query returned no rows.")
        return
    numeric = rows.select_dtypes("number").columns.tolist()
    labels = [c for c in rows.columns if c not in numeric]
    if len(rows) == 1 and len(rows.columns) <= 3 and numeric:
        col = answer_column if answer_column in numeric else numeric[0]
        st.metric(col.replace("_", " ").capitalize(), _format(col, rows[col].iloc[0]), border=True)
        if len(rows.columns) > 1:
            st.dataframe(rows, hide_index=True, width="stretch")
        return
    if labels and numeric and len(rows) <= 30:
        value = answer_column if answer_column in numeric else numeric[0]
        fig = go.Figure(
            go.Bar(
                x=rows[value],
                y=rows[labels[0]].astype(str),
                orientation="h",
                marker=dict(color=ACCENT, line=dict(color=SURFACE, width=2)),
                hovertemplate="%{y}: %{x:,.4g}<extra></extra>",
            )
        )
        fig.update_layout(yaxis_autorange="reversed", xaxis_title=value.replace("_", " "))
        chart(fig, max(220, 32 * len(rows) + 80))
    st.dataframe(rows, hide_index=True, width="stretch")


def _format(column: str, value: float) -> str:
    name = column.lower()
    if "gbp" in name or "commission" in name or "revenue" in name or "gbv" in name:
        return f"£{value:,.0f}"
    if "rate" in name or "share" in name or "pct" in name:
        return f"{value:.1%}" if abs(value) <= 1.5 else f"{value:.1f}%"
    return f"{value:,.4g}"


def _technical(entry: dict[str, Any]) -> None:
    with st.expander("SQL and technical details"):
        if entry.get("sql"):
            st.markdown(
                "**Query that produced the answer**"
                + (" (self-repaired after an error)" if entry.get("repaired") else "")
            )
            st.code(entry["sql"], language="sql")
        if entry.get("alternative_sql"):
            st.markdown("**Independent query written by a separate check**")
            st.code(entry["alternative_sql"], language="sql")
        st.caption(
            f"Model {entry.get('model', '–')} · prompt {entry.get('prompt_version', '–')} · "
            f"{entry.get('latency_ms', 0):,} ms · {entry.get('input_tokens', 0):,} tokens in / "
            f"{entry.get('output_tokens', 0):,} out"
        )


def highlight_numbers(text: str, unmatched: list[str]) -> str:
    """HTML-escape text and mark numbers the checker could not find in the metrics JSON."""
    out = html.escape(text)
    for token in sorted(set(unmatched), key=len, reverse=True):
        safe = html.escape(token)
        out = re.sub(
            re.escape(safe),
            f'<span style="color:#d03b3b;font-weight:600" '
            f'title="Not found in the metrics">{safe}</span>',
            out,
        )
    return out


def render_memo(cached: dict[str, Any]) -> None:
    memo, unmatched = cached["memo"], cached.get("unmatched", [])
    if cached.get("passed"):
        st.success("✅ Every number in this memo was checked against the computed metrics.")
    else:
        st.warning(
            f"⚠️ {len(unmatched)} number(s) could not be found in the metrics and are "
            "highlighted in red."
        )
    st.markdown(f"#### {highlight_numbers(memo['headline'], unmatched)}", unsafe_allow_html=True)
    for item in memo.get("insights", []):
        st.markdown(
            f'<div class="sg-insight"><b>{highlight_numbers(item["title"], unmatched)}</b><br>'
            f"<span>{highlight_numbers(item['detail'], unmatched)}</span></div>",
            unsafe_allow_html=True,
        )
    st.markdown("**Recommendations**")
    recs = pd.DataFrame(memo.get("recommendations", []))
    if not recs.empty:
        st.dataframe(
            recs.rename(
                columns={"action": "Action", "owner": "Owner", "expected_impact": "Expected impact"}
            ),
            hide_index=True,
            width="stretch",
        )
    st.caption(
        f"Written by {cached.get('model', '–')} (prompt {cached.get('prompt_version', '–')}) "
        "from a "
        f"JSON snapshot of the metrics on {cached.get('generated_at', '–')}; "
        f"{cached.get('attempts', 1)} attempt(s)."
    )
