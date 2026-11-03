"""Agent Ops: workload, conversion and response time across the booking-manager team."""

import plotly.graph_objects as go
import streamlit as st

from stayguard.ui import data
from stayguard.ui.layout import chart, footer, how_calculated, page
from stayguard.ui.theme import ACCENT, NEUTRAL, SURFACE

f = page(
    "Agent ops",
    "Who is converting, who is overloaded, and what slow responses cost.",
    "🧑‍💼",
)
board = data.query("06_agent_leaderboard")
skipped = [
    n
    for n, v in (
        ("Country", f.countries),
        ("City", f.cities),
        ("Intake", f.intakes),
        ("Channel", f.channels),
    )
    if v
]

# --- Load vs cancellation -------------------------------------------------------------------------
top2 = board.nsmallest(2, "load_rank")
others = board.drop(top2.index)
st.subheader(
    f"{top2.iloc[0]['agent_name']} and {top2.iloc[1]['agent_name']} carry "
    f"{top2['load_days'].mean() / others['load_days'].median():.1f}x the typical backlog, "
    "and their students cancel more"
)
fig = go.Figure()
fig.add_scatter(
    x=others["load_days"],
    y=others["cancellation_pct"],
    mode="markers",
    name="Other agents",
    marker=dict(size=10, color=NEUTRAL, line=dict(color=SURFACE, width=2)),
    text=others["agent_name"],
    hovertemplate="%{text}<br>%{x:.2f} days of backlog · %{y:.1f}% cancel<extra></extra>",
)
fig.add_scatter(
    x=top2["load_days"],
    y=top2["cancellation_pct"],
    mode="markers+text",
    name="Most overloaded",
    marker=dict(size=12, color=ACCENT, line=dict(color=SURFACE, width=2)),
    text=top2["agent_name"],
    textposition="middle left",
    hovertemplate="%{text}<br>%{x:.2f} days of backlog · %{y:.1f}% cancel<extra></extra>",
)
fig.update_layout(
    xaxis_title="Open bookings ÷ daily call capacity (days of backlog)",
    yaxis_title="Cancellation rate, past intakes (%)",
)
chart(fig, 380)
how_calculated(
    ["06_agent_leaderboard"],
    skipped=skipped,
    note="One row per agent across all markets; the sidebar filters do not apply here.",
)

left, right = st.columns([3, 2])
with left:
    st.subheader("Leaderboard")
    st.dataframe(
        board[
            [
                "conversion_rank",
                "agent_name",
                "team",
                "conversion_pct",
                "median_first_response_minutes",
                "cancellation_pct",
                "open_bookings",
                "load_days",
                "conversion_quartile",
            ]
        ],
        column_config={
            "conversion_rank": st.column_config.NumberColumn("#", width="small"),
            "agent_name": "Agent",
            "team": "Team",
            "conversion_pct": st.column_config.NumberColumn("Conversion", format="%.1f%%"),
            "median_first_response_minutes": st.column_config.NumberColumn(
                "Median reply (min)", format="%.0f"
            ),
            "cancellation_pct": st.column_config.NumberColumn("Cancellations", format="%.1f%%"),
            "open_bookings": st.column_config.NumberColumn("Open bookings"),
            "load_days": st.column_config.NumberColumn("Backlog (days)", format="%.2f"),
            "conversion_quartile": st.column_config.NumberColumn(
                "Quartile", help="1 = best quarter"
            ),
        },
        hide_index=True,
        width="stretch",
        height=420,
    )
with right:
    resp = data.query("08_response_time_vs_conversion")
    fastest, slowest = resp.iloc[0], resp.iloc[-1]
    st.subheader(
        f"Leads answered within {fastest['max_minutes']:.0f} min convert at "
        f"{fastest['conversion_pct']:.1f}%; the slowest fifth at {slowest['conversion_pct']:.1f}%"
    )
    labels = [f"{r.min_minutes:.0f}–{r.max_minutes:,.0f} min" for r in resp.itertuples()]
    fig = go.Figure(
        go.Bar(
            x=labels,
            y=resp["conversion_pct"],
            marker=dict(
                color=[NEUTRAL] * (len(resp) - 1) + [ACCENT], line=dict(color=SURFACE, width=2)
            ),
            hovertemplate="First reply %{x}: %{y:.1f}% book<extra></extra>",
        )
    )
    fig.update_layout(yaxis_ticksuffix="%", xaxis_title="Time to first reply (fifths of leads)")
    chart(fig, 330)
    how_calculated(
        ["08_response_time_vs_conversion"],
        resp,
        skipped=skipped,
        note=f"{slowest['pct_over_sla']:.0f}% of the slowest fifth breach the 240-minute SLA.",
    )
footer()
