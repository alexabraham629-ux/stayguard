"""Revenue at Risk: where open-intake commission is exposed, and how good the risk score is."""

import plotly.graph_objects as go
import streamlit as st

from stayguard.ui import data
from stayguard.ui.layout import apply, chart, footer, gbp, how_calculated, page, pct
from stayguard.ui.theme import ACCENT, CRITICAL, INK_SECONDARY, NEUTRAL, SURFACE

f = page(
    "Revenue at risk",
    "Open Jan-2027 bookings, scored for the chance they cancel before move-in.",
    "⚠️",
)
queue, q_applied, q_skipped = apply(data.query("13_action_queue"), f)
risk_tab, model_tab = st.tabs(["Where the risk is", "How good is the risk score?"])

FRIENDLY = {
    "positive_touch_rate_before_as_of": "Replies to our calls and messages",
    "touches_before_as_of": "Number of contacts since booking",
    "days_booked_before_intake": "How early they booked",
    "visa_status_at_booking": "Visa status",
    "source_country": "Home country",
    "deposit_paid": "Deposit paid",
    "channel": "How they found us",
    "agent_load_vs_team": "Their agent's workload",
    "level": "Undergraduate or postgraduate",
    "has_guarantor": "Has a guarantor",
}

with risk_tab:
    if queue.empty:
        st.info("No open bookings match the filters.")
    else:
        rar = queue["expected_loss_gbp"].sum()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Revenue at risk", gbp(rar), border=True)
        c2.metric("Open bookings", f"{len(queue):,}", border=True)
        c3.metric("Average risk of cancelling", pct(queue["p_cancel"].mean()), border=True)
        high = (queue["p_cancel"] >= 0.3).mean()
        c4.metric("Bookings with 30%+ risk", pct(high), border=True)

        # Distribution
        st.subheader(
            f"Risk is concentrated: 1 in {round(1 / high) if high else '–'} open bookings has a "
            "30%+ chance of cancelling"
        )
        fig = go.Figure(
            go.Histogram(
                x=queue["p_cancel"] * 100,
                xbins=dict(start=0, end=100, size=5),
                marker=dict(color=ACCENT, line=dict(color=SURFACE, width=2)),
                hovertemplate="%{x}% risk: %{y} bookings<extra></extra>",
            )
        )
        fig.add_vline(x=30, line=dict(color=INK_SECONDARY, width=1))
        fig.update_layout(xaxis_title="Predicted chance of cancelling (%)", yaxis_title="Bookings")
        chart(fig, 300)
        how_calculated(
            ["13_action_queue"], queue[["booking_id", "city", "p_cancel"]], q_applied, q_skipped
        )

        left, right = st.columns(2)
        with left:
            cities, applied, skipped = apply(data.query("07_revenue_at_risk_by_city"), f)
            cities = cities.sort_values("revenue_at_risk_gbp")
            top = cities.iloc[-1]
            share = top["revenue_at_risk_gbp"] / cities["revenue_at_risk_gbp"].sum()
            st.subheader(f"{top['city']} carries {share:.0%} of revenue at risk")
            fig = go.Figure(
                go.Bar(
                    y=cities["city"],
                    x=cities["revenue_at_risk_gbp"],
                    orientation="h",
                    marker=dict(
                        color=[ACCENT if c == top["city"] else NEUTRAL for c in cities["city"]],
                        line=dict(color=SURFACE, width=2),
                    ),
                    hovertemplate="%{y}: %{x:£,.0f}<extra></extra>",
                )
            )
            fig.update_layout(xaxis_tickprefix="£", xaxis_tickformat=".3~s")
            chart(fig, 380)
            how_calculated(["07_revenue_at_risk_by_city"], cities, applied, skipped)
        with right:
            by_visa = (
                queue.groupby("visa_status_at_booking")["expected_loss_gbp"]
                .agg(["sum", "size"])
                .rename(columns={"sum": "revenue_at_risk_gbp", "size": "bookings"})
                .sort_values("revenue_at_risk_gbp")
            )
            unresolved = (
                by_visa.loc[
                    by_visa.index.isin(["pending", "not_applied"]), "revenue_at_risk_gbp"
                ].sum()
                / by_visa["revenue_at_risk_gbp"].sum()
            )
            st.subheader(f"Unresolved visas account for {unresolved:.0%} of revenue at risk")
            fig = go.Figure(
                go.Bar(
                    y=by_visa.index.str.replace("_", " "),
                    x=by_visa["revenue_at_risk_gbp"],
                    orientation="h",
                    marker=dict(
                        color=[
                            CRITICAL if s in ("pending", "not_applied") else NEUTRAL
                            for s in by_visa.index
                        ],
                        line=dict(color=SURFACE, width=2),
                    ),
                    hovertemplate="visa %{y}: %{x:£,.0f}<extra></extra>",
                )
            )
            fig.update_layout(xaxis_tickprefix="£", xaxis_tickformat=".3~s")
            chart(fig, 220)
            by_country = (
                queue.groupby("source_country")["expected_loss_gbp"].sum().sort_values().tail(6)
            )
            st.markdown(
                f"**By home country:** {by_country.index[-1]} students carry the most risk "
                f"({gbp(by_country.iloc[-1])})"
            )
            fig = go.Figure(
                go.Bar(
                    y=by_country.index,
                    x=by_country.to_numpy(),
                    orientation="h",
                    marker=dict(color=ACCENT, line=dict(color=SURFACE, width=2)),
                    hovertemplate="%{y}: %{x:£,.0f}<extra></extra>",
                )
            )
            fig.update_layout(xaxis_tickprefix="£", xaxis_tickformat=".3~s")
            chart(fig, 230)
            how_calculated(
                ["13_action_queue"],
                by_visa.reset_index(),
                q_applied,
                q_skipped,
                note="Revenue at risk = commission x predicted risk, summed over open bookings.",
            )

with model_tab:
    ev = data.table("model_evaluation")
    version = data.table("scored_bookings")["model_version"].iloc[0]
    validation = [s for s in ev["dataset"].unique() if s.startswith("validation")][0]

    def metric(model: str, name: str) -> float:
        row = ev[(ev["model"] == model) & (ev["metric"] == name) & (ev["dataset"] == validation)]
        return float(row["value"].iloc[0])

    model = "logistic_regression" if version.startswith("logreg") else "gradient_boosting"
    st.markdown(
        f"We tested the score on **{validation.split()[1]}**, an intake the model never saw, "
        "and compared it with what really happened."
    )
    c1, c2, c3 = st.columns(3)
    c1.metric(
        "Cancellations caught in the riskiest 10%",
        pct(metric(model, "gains_top_decile"), 0),
        help="Calling the top tenth by risk reaches this share of all the bookings that "
        "went on to cancel.",
        border=True,
    )
    c2.metric(
        "Riskiest 10% vs average",
        f"{metric(model, 'lift_top_decile'):.1f}x",
        help="How much more often the riskiest tenth cancelled than the average booking.",
        border=True,
    )
    saved, baseline_saved = metric(model, "saved_gbp"), metric("baseline_segment_rate", "saved_gbp")
    c3.metric(
        "Commission saved by calling the top 20%",
        gbp(saved),
        delta=f"{saved / baseline_saved - 1:+.0%} vs a simple rule of thumb",
        help="At the assumed 25% save rate. The rule of thumb scores bookings by visa status, "
        "deposit and lead time only.",
        border=True,
    )

    left, right = st.columns(2)
    with left:
        cal = data.table("model_calibration").query("model == @model")
        st.subheader("When the score says 20%, about 20% cancel")
        fig = go.Figure()
        fig.add_scatter(
            x=[0, 50],
            y=[0, 50],
            mode="lines",
            name="Perfect score",
            line=dict(color=NEUTRAL, width=1),
            hoverinfo="skip",
        )
        fig.add_scatter(
            x=cal["mean_predicted"] * 100,
            y=cal["observed_rate"] * 100,
            name="StayGuard score",
            mode="lines+markers",
            line=dict(color=ACCENT, width=2),
            marker=dict(size=9, line=dict(color=SURFACE, width=2)),
            hovertemplate="Predicted %{x:.0f}% → actually %{y:.0f}% cancelled<extra></extra>",
        )
        fig.update_layout(
            xaxis_title="Predicted chance of cancelling (%)",
            yaxis_title="Share that actually cancelled (%)",
        )
        chart(fig, 340)
        how_calculated(
            ["model calibration table (src/stayguard/model/evaluate.py)"],
            cal,
            note="Validation bookings split into 10 equal groups by predicted risk.",
        )
    with right:
        imp = data.table("model_importance").head(8).iloc[::-1]
        st.subheader("Engagement, visa and deposit drive the score")
        fig = go.Figure(
            go.Bar(
                y=[FRIENDLY.get(x, x) for x in imp["feature"]],
                x=imp["importance_mean"],
                orientation="h",
                marker=dict(color=ACCENT, line=dict(color=SURFACE, width=2)),
                hovertemplate="%{y}<extra></extra>",
            )
        )
        fig.update_layout(xaxis_title="How much worse the score gets without it")
        chart(fig, 340)
        how_calculated(
            ["model permutation importance (src/stayguard/model/evaluate.py)"],
            data.table("model_importance"),
            note="Shuffle one input at a time on validation bookings and measure the drop "
            "in PR-AUC.",
        )
    st.caption(
        f"Model `{version}`, trained on intakes before {validation.split()[1]}, refit on all "
        "closed intakes to score Jan-2027. Details: docs/FINDINGS.md."
    )
footer()
