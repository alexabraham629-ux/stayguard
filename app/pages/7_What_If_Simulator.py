"""What-If Simulator: how much expected net commission can ops and policy levers add?"""

import plotly.graph_objects as go
import streamlit as st

from stayguard.calendar import open_intake
from stayguard.sim.whatif import WhatIfInputs, open_bookings, pipeline_stats, simulate
from stayguard.ui import data
from stayguard.ui.layout import chart, footer, gbp, how_calculated, page, pct
from stayguard.ui.theme import ACCENT, GOOD, INK_SECONDARY

f = page(
    "What-if simulator",
    "Move the levers to see how much more of the open intake's commission could land. "
    "Projections from assumptions, not forecasts: every assumption is shown below.",
    "🎛️",
)
d = data.metric_data()
ops = d.assumptions["operations"]
bookings = open_bookings(d, f)
stats = pipeline_stats(d, f)
now = open_intake(d.assumptions)

controls, result = st.columns([1, 2])
with controls:
    st.markdown("**Ops**")
    share = st.slider(
        "Share of open bookings the team calls",
        0,
        100,
        int(ops["queue_top_share"] * 100),
        5,
        format="%d%%",
        help="Highest expected-loss bookings first (the action queue).",
    )
    save = st.slider(
        "Save rate when a call is made",
        0,
        60,
        int(ops["intervention_save_rate"] * 100),
        5,
        format="%d%%",
        help="Share of a called booking's at-risk commission kept. ASSUMPTION.",
    )
    sla = st.slider(
        "Leads answered within 240 minutes",
        int(stats.current_sla_share * 100),
        100,
        int(stats.current_sla_share * 100),
        1,
        format="%d%%",
        help=f"Today: {stats.current_sla_share:.0%} of leads (past intakes).",
    )
    st.markdown("**Policy**")
    deposit = st.slider(
        "No-deposit students who pay a deposit when asked",
        0,
        100,
        0,
        5,
        format="%d%%",
        help="Their risk falls to the model's prediction for the same booking with a deposit.",
    )

r = simulate(bookings, stats, WhatIfInputs(share / 100, save / 100, deposit / 100, sla / 100))
with result:
    gain = r.projected_enc_gbp - r.base_enc_gbp
    st.subheader(
        f"These levers add {gbp(gain)} ({gain / r.base_enc_gbp:+.1%}) to {now} "
        "expected net commission"
        if r.base_enc_gbp
        else "No open bookings match the filters"
    )
    fig = go.Figure(
        go.Waterfall(
            x=["Expected today", "Chase deposits", "Work the queue", "Faster replies", "Projected"],
            measure=["absolute", "relative", "relative", "relative", "total"],
            y=[r.base_enc_gbp, r.deposit_gain_gbp, r.calls_gain_gbp, r.sla_gain_gbp, 0],
            increasing=dict(marker=dict(color=GOOD)),
            totals=dict(marker=dict(color=ACCENT)),
            connector=dict(line=dict(color=INK_SECONDARY, width=1)),
            text=[
                gbp(v)
                for v in (
                    r.base_enc_gbp,
                    r.deposit_gain_gbp,
                    r.calls_gain_gbp,
                    r.sla_gain_gbp,
                    r.projected_enc_gbp,
                )
            ],
            textposition="outside",
            hovertemplate="%{x}: %{y:£,.0f}<extra></extra>",
        )
    )
    low = r.base_enc_gbp * 0.9
    fig.update_layout(
        yaxis_range=[low, r.projected_enc_gbp * 1.04 if r.projected_enc_gbp else 1],
        yaxis_tickprefix="£",
        yaxis_tickformat=",.0s",
    )
    chart(fig, 380)
    st.caption(
        f"{r.calls_made:,} calls · {r.deposits_collected:.0f} deposits collected · "
        f"{stats.open_pipeline_leads:,} {now} leads still in the pipeline. "
        "The y-axis starts at 90% of today's expected commission so the changes are visible."
    )

st.subheader("Assumptions behind the projection")
st.table(
    {
        "Lever": [
            "Work the queue",
            "Work the queue",
            "Chase deposits",
            "Faster replies",
            "Faster replies",
            "Faster replies",
        ],
        "Assumption": [
            "Calls go to the highest expected-loss bookings first",
            f"A call keeps {save}% of that booking's at-risk commission",
            "A deposit lowers risk as much as the model sees in past data (correlation, not proof)",
            f"Leads answered in time convert like past fast-answered leads "
            f"({pct(stats.conversion_within_sla)} vs {pct(stats.conversion_outside_sla)})",
            f"Each new booking is worth the average open booking ({gbp(stats.avg_commission_gbp)})",
            f"…and survives like today's open bookings ({pct(stats.avg_survival)})",
        ],
        "Source": [
            "sql/13_action_queue.sql",
            "config/assumptions.yaml (editable here)",
            "scored_bookings.p_cancel_if_deposit",
            "sql/08_response_time_vs_conversion.sql",
            "metrics.py",
            "scored_bookings.p_cancel",
        ],
    }
)
how_calculated(
    ["13_action_queue", "08_response_time_vs_conversion", "metrics.expected_net_commission_gbp"],
    note="Levers are applied in order (deposits, then calls on the remaining risk, then new "
    "bookings from faster replies) so nothing is counted twice. Code: src/stayguard/sim/whatif.py.",
)
footer()
