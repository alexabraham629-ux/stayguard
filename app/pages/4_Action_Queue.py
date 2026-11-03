"""Action Queue: who each booking manager should call today, and why."""

import streamlit as st

from stayguard.ui import data
from stayguard.ui.layout import apply, footer, gbp, how_calculated, page

f = page(
    "Action queue",
    "Today's call list: open bookings ranked by expected commission loss, within each agent's "
    "daily capacity.",
    "📞",
)
queue, applied, skipped = apply(data.query("13_action_queue"), f)

col_team, col_agent, col_toggle = st.columns([2, 2, 1], vertical_alignment="bottom")
teams = col_team.multiselect("Team", sorted(queue["team"].unique()), placeholder="All teams")
pool = queue.loc[queue["team"].isin(teams)] if teams else queue
agents = col_agent.multiselect(
    "Agent", sorted(pool["agent_name"].unique()), placeholder="All agents"
)
today_only = col_toggle.toggle("Today's calls only", value=True)

view = pool.loc[pool["agent_name"].isin(agents)] if agents else pool
overflow = view.loc[~view["call_today"]]
if today_only:
    view = view.loc[view["call_today"]]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Calls in this list", f"{len(view):,}", border=True)
c2.metric("Expected loss covered", gbp(view["expected_loss_gbp"].sum()), border=True)
c3.metric(
    "Saveable if called",
    gbp(view["saveable_if_called_gbp"].sum()),
    help="Expected loss x the assumed 25% save rate (config/assumptions.yaml).",
    border=True,
)
c4.metric(
    "Over capacity today",
    f"{len(overflow):,}",
    help="Bookings beyond their agent's daily capacity. Reassign within the team.",
    border=True,
)

if len(overflow):
    worst = overflow.groupby("agent_name").size().sort_values(ascending=False)
    # The reassignment advice must come from the most-overflowing agent's OWN team.
    worst_rows = overflow.loc[overflow["agent_name"] == worst.index[0]]
    advice = worst_rows["assignment"].iloc[0].split(": ", 1)[1]
    st.warning(
        f"{len(overflow)} high-value calls don't fit today. Most overflow sits with "
        f"{worst.index[0]} ({worst.iloc[0]} calls): {advice}.",
        icon="⚠️",
    )

st.subheader("Call list")
columns = {
    "priority_rank": st.column_config.NumberColumn("#", width="small"),
    "agent_name": st.column_config.TextColumn("Agent"),
    "city": "City",
    "commission_gbp": st.column_config.NumberColumn("Commission", format="£%.0f"),
    "p_cancel": st.column_config.ProgressColumn(
        "Risk of cancelling", format="percent", min_value=0.0, max_value=1.0
    ),
    "expected_loss_gbp": st.column_config.NumberColumn("Expected loss", format="£%.0f"),
    "reason_codes": st.column_config.TextColumn("Why call", width="large"),
    "assignment": st.column_config.TextColumn("Assignment", width="medium"),
    "source_country": "Home country",
    "team": "Team",
    "booking_id": st.column_config.NumberColumn("Booking", format="%d"),
}
st.dataframe(
    view[list(columns)],
    column_config=columns,
    hide_index=True,
    width="stretch",
    height=520,
)
st.download_button(
    "Download this list (CSV)",
    view[list(columns)].to_csv(index=False).encode("utf-8"),
    file_name="stayguard_call_list.csv",
    mime="text/csv",
)
how_calculated(
    ["13_action_queue"],
    applied=applied,
    skipped=skipped,
    note="Expected loss = commission x predicted risk. Each agent's calls today are their "
    "highest-loss bookings up to their daily capacity; the rest are flagged for reassignment. "
    "Reason codes are the risk drivers the model weighs most (ADR-020).",
)
footer()
