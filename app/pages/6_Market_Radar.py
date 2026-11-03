"""Market Radar: demand shifts, channel economics and price sensitivity."""

import plotly.graph_objects as go
import streamlit as st

from stayguard.ui import data
from stayguard.ui.layout import apply, chart, footer, how_calculated, page
from stayguard.ui.theme import ACCENT, DIVERGING_NEG, DIVERGING_POS, NEUTRAL, SURFACE

f = page(
    "Market radar",
    "Where demand is softening, which channels pay, and whether price holds students back.",
    "📡",
)

# --- YoY PG demand ------------------------------------------------------------------------------
pg, applied, skipped = apply(data.query("11_yoy_pg_demand_by_city"), f)
years = sorted(pg["academic_year"].unique())
year = st.segmented_control(
    "Academic year", years[1:], default=years[1], help="Compared with the year before."
)
year = year or years[1]
seg = pg.groupby(["segment", "academic_year"])["pg_bookings"].sum().unstack()
prev = years[years.index(year) - 1]
change = (seg[year] / seg[prev] - 1).dropna()
parts = [f"{s} {v:+.0%}" for s, v in change.sort_values().items()]
st.subheader(f"Postgraduate bookings {year} vs {prev}: " + " · ".join(parts))
rows = pg.loc[pg["academic_year"] == year].sort_values("yoy_change_pct")
fig = go.Figure(
    go.Bar(
        y=rows["city"],
        x=rows["yoy_change_pct"],
        orientation="h",
        marker=dict(
            color=[DIVERGING_NEG if v < 0 else DIVERGING_POS for v in rows["yoy_change_pct"]],
            line=dict(color=SURFACE, width=2),
        ),
        customdata=rows[["prev_year_pg_bookings", "pg_bookings"]],
        hovertemplate="%{y}: %{x:+.1f}% (%{customdata[0]} → %{customdata[1]})<extra></extra>",
    )
)
fig.update_layout(xaxis_ticksuffix="%", xaxis_title=f"Change in PG bookings vs {prev}")
chart(fig, 400)
how_calculated(
    ["11_yoy_pg_demand_by_city"],
    pg,
    applied,
    skipped,
    note="Like-for-like: January bookings are counted to the same point before move-in as "
    "today, because Jan-2027 is still open.",
)

left, right = st.columns(2)
with left:
    ch, applied, skipped = apply(data.query("12_channel_unit_economics"), f)
    ch = ch.sort_values("realised_commission_per_lead_gbp")
    best, worst = ch.iloc[-1], ch.iloc[0]

    def a_or_an(word: str) -> str:
        return f"{'An' if word[0] in 'aeiou' else 'A'} {word}"

    best_name, worst_name = best["channel"].replace("_", " "), worst["channel"].replace("_", " ")
    st.subheader(
        f"{a_or_an(best_name)} lead is worth £{best['realised_commission_per_lead_gbp']:.0f} in "
        f"landed commission; a {worst_name} lead £{worst['realised_commission_per_lead_gbp']:.0f}"
    )
    fig = go.Figure(
        go.Bar(
            y=ch["channel"].str.replace("_", " "),
            x=ch["realised_commission_per_lead_gbp"],
            orientation="h",
            marker=dict(
                color=[ACCENT if c == best["channel"] else NEUTRAL for c in ch["channel"]],
                line=dict(color=SURFACE, width=2),
            ),
            customdata=ch[["conversion_pct", "cancellation_pct"]],
            hovertemplate="%{y}: £%{x:.0f} per lead<br>converts %{customdata[0]:.1f}% · "
            "cancels %{customdata[1]:.1f}%<extra></extra>",
        )
    )
    fig.update_layout(xaxis_tickprefix="£", xaxis_title="Landed commission per lead")
    chart(fig, 330)
    how_calculated(["12_channel_unit_economics"], ch, applied, skipped)

with right:
    bands = data.query("16_budget_band_vs_conversion")
    spread = bands["conversion_pct"].max() - bands["conversion_pct"].min()
    low, high = bands.iloc[0], bands.iloc[-1]
    st.subheader(
        f"Budget barely moves conversion (within {spread:.1f} points across bands); "
        f"lower-budget students cancel slightly more ({low['cancellation_pct']:.1f}% vs "
        f"{high['cancellation_pct']:.1f}%)"
    )
    fig = go.Figure()
    fig.add_bar(
        x=bands["band_label"],
        y=bands["conversion_pct"],
        name="Book (% of leads)",
        marker=dict(color=ACCENT, line=dict(color=SURFACE, width=2)),
        hovertemplate="%{x}: %{y:.1f}% of leads book<extra></extra>",
    )
    fig.add_bar(
        x=bands["band_label"],
        y=bands["cancellation_pct"],
        name="Cancel (% of bookings)",
        marker=dict(color=NEUTRAL, line=dict(color=SURFACE, width=2)),
        hovertemplate="%{x}: %{y:.1f}% of bookings cancel<extra></extra>",
    )
    fig.update_layout(barmode="group", yaxis_ticksuffix="%", xaxis_title="Student's weekly budget")
    chart(fig, 330)
    how_calculated(
        ["16_budget_band_vs_conversion"],
        bands,
        skipped=[
            n
            for n, v in (
                ("Country", f.countries),
                ("City", f.cities),
                ("Intake", f.intakes),
                ("Channel", f.channels),
            )
            if v
        ],
    )
footer()
