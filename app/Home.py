"""Executive Overview: what will land from the open intake, and what needs attention."""

import plotly.graph_objects as go
import streamlit as st

from stayguard.ai.memo import load_memo
from stayguard.calendar import (
    comparable_intake,
    days_to_open_intake,
    latest_closed_intake,
    open_intake,
)
from stayguard.kpis import commission_by_intake, executive_kpis, headline_insights
from stayguard.ui import data
from stayguard.ui.ai_render import render_memo
from stayguard.ui.layout import chart, footer, gbp, how_calculated, insight, kpi_card, page
from stayguard.ui.theme import ACCENT, CRITICAL, NEUTRAL, SURFACE

f = page(
    "Executive overview",
    "How much booked commission will really land, and where it is at risk. "
    "Like-for-like comparisons with the same intake a year earlier.",
    "🏠",
)
d = data.metric_data()
now = open_intake(d.assumptions)

# --- KPI cards ------------------------------------------------------------------------------------
kpis = executive_kpis(d, f)
st.caption(
    f"Money cards: **{now}**, the open intake ({days_to_open_intake(d.assumptions)} days to "
    f"move-in), against {comparable_intake(now)} at the same point. Rate cards: "
    f"**{latest_closed_intake(d.assumptions)}**, the latest intake that has moved in, against "
    "the year before."
)
for col, k in zip(st.columns(len(kpis)), kpis, strict=True):
    with col:
        kpi_card(k)
if f.intakes:
    st.caption(
        "KPI cards are pinned to their intakes, so the Intake filter does not apply to them."
    )

# --- Commission by intake -------------------------------------------------------------------------
by_intake = commission_by_intake(d, f)
open_row = by_intake.loc[by_intake["intake"] == now]
if len(open_row):
    o = open_row.iloc[0]
    share = o["landed_or_expected_gbp"] / (o["landed_or_expected_gbp"] + o["lost_or_at_risk_gbp"])
    title = (
        f"{now} is expected to land {gbp(o['landed_or_expected_gbp'])} of the "
        f"{gbp(o['landed_or_expected_gbp'] + o['lost_or_at_risk_gbp'])} still open ({share:.0%})"
    )
else:
    title = "Commission landed and lost, by intake"
st.subheader(title)

closed = by_intake["is_closed"]
fig = go.Figure()
fig.add_bar(
    x=by_intake["intake"],
    y=by_intake["landed_or_expected_gbp"],
    name="Landed (closed) / expected to land (open)",
    marker=dict(color=ACCENT, line=dict(color=SURFACE, width=2)),
    marker_pattern_shape=["" if c else "/" for c in closed],
    hovertemplate="%{x}<br>%{y:£,.0f}<extra>landed / expected</extra>",
)
fig.add_bar(
    x=by_intake["intake"],
    y=by_intake["lost_or_at_risk_gbp"],
    name="Lost to cancellation (closed) / at risk (open)",
    marker=dict(
        color=[NEUTRAL if c else CRITICAL for c in closed], line=dict(color=SURFACE, width=2)
    ),
    hovertemplate="%{x}<br>%{y:£,.0f}<extra>lost / at risk</extra>",
)
fig.update_layout(barmode="stack", yaxis_tickprefix="£", yaxis_tickformat=".3~s")
chart(fig, 360)
st.caption(
    f"Hatched bar: {now} is still open, so it shows expected net commission and revenue at risk "
    "for bookings not yet cancelled; earlier intakes show what actually happened."
)
how_calculated(
    ["15_commission_by_intake", "metrics.realised_commission_gbp / expected_net_commission_gbp"],
    by_intake,
    applied=[
        n for n, v in (("Country", f.countries), ("City", f.cities), ("Channel", f.channels)) if v
    ],
    note="The SQL file returns the unfiltered totals; tests/test_sql.py reconciles them "
    "with metrics.py.",
)

# --- Insights ----------------------------------------------------------------------------------
st.subheader("This week's memo")
memo = load_memo()
if memo is not None:
    render_memo(memo)
    st.caption("All markets. Regenerate with `make ai-memo`.")
else:
    for item in headline_insights(data.query):
        insight(item.headline, item.detail + f" · <code>sql/{item.sql_file}.sql</code>")
    st.caption(
        "Rule-based insights from the SQL library, all markets. Run `make ai-memo` (needs an API "
        "key) to replace them with an AI-written memo whose every number is checked."
    )
footer()
