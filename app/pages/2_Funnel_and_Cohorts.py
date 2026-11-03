"""Funnel & Cohorts: where students drop out, and when bookings cancel."""

import plotly.graph_objects as go
import streamlit as st

from stayguard.ui import data
from stayguard.ui.layout import apply, chart, footer, how_calculated, page
from stayguard.ui.theme import ACCENT, SEQUENTIAL, SURFACE, intake_colors

f = page(
    "Funnel & cohorts",
    "From enquiry to move-in: which step loses the most students, and how quickly bookings cancel.",
    "🔻",
)
intakes = list(data.assumptions()["intakes"])

# --- Funnel ---------------------------------------------------------------------------------------
funnel, applied, skipped = apply(data.query("01_funnel_by_city_intake"), f)
closed = funnel.loc[funnel["is_closed_intake"]]
stages = ["leads", "contacted", "shortlisted", "booked", "moved_in"]
labels = ["Enquired", "Contacted", "Shortlisted", "Booked", "Moved in"]
totals = closed[stages].sum()
if totals["leads"] > 0:
    step_loss = {
        f"{labels[i]} → {labels[i + 1]}": 1 - totals[stages[i + 1]] / totals[stages[i]]
        for i in range(len(stages) - 1)
    }
    worst_step = max(step_loss, key=step_loss.get)
    st.subheader(
        f"{totals['booked'] / totals['leads']:.0%} of enquiries book; the biggest drop is "
        f"{worst_step} ({step_loss[worst_step]:.0%} lost)"
    )
    fig = go.Figure(
        go.Funnel(
            y=labels,
            x=totals.to_numpy(),
            texttemplate="%{value:,}<br>%{percentInitial:.0%}",
            marker=dict(color=ACCENT, line=dict(color=SURFACE, width=2)),
            connector=dict(fillcolor="#e1e0d9"),
            hovertemplate="%{y}: %{x:,}<extra></extra>",
        )
    )
    chart(fig, 330)
st.caption("Intakes that have moved in only, so every stage, including move-in, is final.")
how_calculated(["01_funnel_by_city_intake"], closed, applied, skipped)

left, right = st.columns(2)

# --- Cohort cancellation curves -------------------------------------------------------------------
with left:
    curves, applied, skipped = apply(data.query("03_cohort_cancellation_curve"), f)
    colors = intake_colors(intakes)
    finals = curves.groupby("intake")["cumulative_cancellation_pct"].max()
    early = curves.loc[curves["bucket_order"] == 2].set_index("intake")[
        "cumulative_cancellation_pct"
    ]
    closed_intakes = curves.loc[curves["is_closed_intake"], "intake"].unique()
    if len(closed_intakes):
        early_share = (early[closed_intakes] / finals[closed_intakes]).mean()
        st.subheader(f"{early_share:.0%} of cancellations happen within 30 days of booking")
    fig = go.Figure()
    for intake in [i for i in intakes if i in curves["intake"].unique()]:
        c = curves.loc[curves["intake"] == intake].sort_values("bucket_order")
        is_open = not c["is_closed_intake"].iloc[0]
        fig.add_scatter(
            x=c["bucket_label"],
            y=c["cumulative_cancellation_pct"],
            name=intake + (" (open)" if is_open else ""),
            mode="lines+markers",
            line=dict(color=colors[intake], width=2, dash="dot" if is_open else "solid"),
            marker=dict(size=8, line=dict(color=SURFACE, width=2)),
            hovertemplate=f"{intake}<br>%{{x}}: %{{y:.1f}}%<extra></extra>",
        )
    fig.update_layout(yaxis_ticksuffix="%", xaxis_title="Days since booking", hovermode="x unified")
    chart(fig, 340)
    how_calculated(
        ["03_cohort_cancellation_curve"],
        curves,
        applied,
        skipped,
        note="Dotted line: the open intake, whose curve is still being written.",
    )

# --- Seasonality heatmap --------------------------------------------------------------------------
with right:
    season, applied, skipped = apply(data.query("17_lead_seasonality"), f)
    peaks = (
        season.loc[season["is_closed_intake"]]
        .groupby(["intake_month", "month_label"])["share_of_intake_pct"]
        .mean()
        .sort_values(ascending=False)
    )
    calendar_order = [
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
    ]

    def top_months(intake_month: str, n: int) -> str:
        if intake_month not in peaks.index:
            return "–"
        months = sorted(peaks.loc[intake_month].head(n).index, key=calendar_order.index)
        return f"{months[0]}–{months[-1]}"

    st.subheader(
        f"Sep-intake enquiries peak {top_months('Sep', 3)}; "
        f"Jan-intake enquiries peak {top_months('Jan', 2)}"
    )
    grid = season.pivot_table(
        index="intake", columns="months_before_intake", values="share_of_intake_pct"
    ).reindex([i for i in intakes if i in season["intake"].unique()])
    grid = grid[sorted(grid.columns, reverse=True)]
    month_names = season.drop_duplicates(["intake", "months_before_intake"]).set_index(
        ["intake", "months_before_intake"]
    )["month_label"]
    text = [[month_names.get((i, m), "") for m in grid.columns] for i in grid.index]
    fig = go.Figure(
        go.Heatmap(
            z=grid.to_numpy(),
            x=[f"{m} mo" for m in grid.columns],
            y=grid.index,
            text=text,
            texttemplate="%{text}",
            colorscale=[[i / (len(SEQUENTIAL) - 1), c] for i, c in enumerate(SEQUENTIAL)],
            xgap=2,
            ygap=2,
            colorbar=dict(title="% of intake", ticksuffix="%"),
            hovertemplate="%{y}, %{text} (%{x} before move-in): %{z:.1f}% of leads<extra></extra>",
        )
    )
    fig.update_layout(xaxis_title="Months before move-in", yaxis_autorange="reversed")
    chart(fig, 340)
    how_calculated(
        ["17_lead_seasonality"],
        season,
        applied,
        skipped,
        note="Jan-2027 is missing Nov–Dec: those enquiries have not happened yet.",
    )
footer()
