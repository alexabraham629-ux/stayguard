"""Page scaffolding: config, sidebar filters, KPI cards, charts, explainers, footer."""

from __future__ import annotations

import math
from collections.abc import Iterable

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from stayguard.kpis import Kpi
from stayguard.metrics import Filters
from stayguard.ui import data
from stayguard.ui.theme import register_template

FILTER_COLUMNS = {
    "countries": "country",
    "cities": "city",
    "intakes": "intake",
    "channels": "channel",
}
FILTER_LABELS = {
    "countries": "Country",
    "cities": "City",
    "intakes": "Intake",
    "channels": "Channel",
}

_CSS = """
<style>
  .block-container {padding-top: 2.2rem; max-width: 1280px;}
  [data-testid="stMetric"] {background: #fcfcfb;}
  [data-testid="stMetricLabel"] p {color: #52514e; font-size: 0.85rem;}
  .sg-kicker {color: #52514e; font-size: 0.95rem; margin-top: -0.6rem; margin-bottom: 1.2rem;}
  .sg-insight {border-left: 3px solid #2a78d6; padding: 0.2rem 0 0.2rem 0.9rem;
               margin-bottom: 0.9rem;}
  .sg-insight b {font-size: 1.02rem;}
  .sg-insight span {color: #52514e; font-size: 0.9rem;}
  .sg-footer {color: #898781; font-size: 0.8rem; text-align: center; padding: 1.5rem 0 0.5rem;}
</style>
"""


def page(title: str, kicker: str, icon: str = "📊") -> Filters:
    """Set up a page and its global sidebar filters; returns the active filters."""
    st.set_page_config(page_title=f"{title} · StayGuard", page_icon=icon, layout="wide")
    register_template()
    st.markdown(_CSS, unsafe_allow_html=True)
    st.title(title)
    st.markdown(f'<div class="sg-kicker">{kicker}</div>', unsafe_allow_html=True)
    return sidebar_filters()


def _persisted_multiselect(key: str, label: str, options: list[str]) -> list[str]:
    """Multiselect whose value survives page switches (widget state is per page in Streamlit)."""
    store = f"_filter_{key}"
    saved = [v for v in st.session_state.get(store, []) if v in options]
    st.session_state[key] = saved

    def keep() -> None:
        st.session_state[store] = st.session_state[key]

    return st.multiselect(label, options, key=key, on_change=keep, placeholder="All")


def sidebar_filters() -> Filters:
    b = data.metric_data().bookings
    with st.sidebar:
        st.markdown("**Filters** · apply to every page")
        countries = _persisted_multiselect("countries", "Country", sorted(b["country"].unique()))
        city_pool = b.loc[b["country"].isin(countries)] if countries else b
        cities = _persisted_multiselect("cities", "City", sorted(city_pool["city"].unique()))
        intakes = _persisted_multiselect("intakes", "Intake", list(data.assumptions()["intakes"]))
        channels = _persisted_multiselect("channels", "Channel", sorted(b["channel"].unique()))
        st.caption("Synthetic data · snapshot 31 Oct 2026")
    return Filters(tuple(countries), tuple(cities), tuple(intakes), tuple(channels))


def apply(df: pd.DataFrame, f: Filters) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Filter a query result on the filter columns it has.

    Returns (rows, applied, not_applicable).
    """
    applied, skipped = [], []
    for attr, column in FILTER_COLUMNS.items():
        values = getattr(f, attr)
        if not values:
            continue
        if column in df.columns:
            df = df.loc[df[column].isin(values)]
            applied.append(FILTER_LABELS[attr])
        else:
            skipped.append(FILTER_LABELS[attr])
    return df, applied, skipped


def gbp(x: float) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "–"
    if abs(x) >= 1_000_000:
        return f"£{x / 1_000_000:.2f}m"
    if abs(x) >= 10_000:
        return f"£{x / 1_000:.0f}k"
    return f"£{x:,.0f}"


def pct(x: float, digits: int = 1) -> str:
    return "–" if x is None or math.isnan(x) else f"{x:.{digits}%}"


def kpi_card(k: Kpi) -> None:
    value = gbp(k.value) if k.unit == "gbp" else pct(k.value)
    shown = round(100 * k.delta, 1) if not math.isnan(k.delta) else math.nan
    if math.isnan(shown):
        delta = None
    elif k.delta_kind == "pct_change":
        delta = f"{shown:+.1f}% {k.comparison_short}"
    else:
        delta = f"{shown:+.1f} pp {k.comparison_short}"
    color = "normal" if k.better_when == "higher" else "inverse"
    st.metric(
        k.label,
        value,
        delta=delta,
        # A change that rounds to zero is neither good nor bad news.
        delta_color="off" if shown == 0 else color,
        help=f"{k.explanation}\n\nCompared {k.comparison}.\n\nComputed by `{k.metric_function}` "
        f"· SQL `sql/{k.sql_file}.sql`",
        border=True,
    )


def insight(headline: str, detail: str) -> None:
    st.markdown(
        f'<div class="sg-insight"><b>{headline}</b><br><span>{detail}</span></div>',
        unsafe_allow_html=True,
    )


def chart(fig: go.Figure, height: int = 340) -> None:
    # Set on the figure itself: Streamlit's front end overrides template background colours.
    fig.update_layout(height=height, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, width="stretch", theme=None, config={"displayModeBar": False})


def how_calculated(
    sql_files: Iterable[str],
    table_view: pd.DataFrame | None = None,
    applied: list[str] | None = None,
    skipped: list[str] | None = None,
    note: str | None = None,
) -> None:
    """The per-chart explainer: which SQL file, which filters, and the data behind it."""
    with st.expander("How this number is calculated"):
        for name in sql_files:
            h = data.header(name) if not name.startswith(("metrics.", "model ")) else {}
            if h:
                st.markdown(f"**`sql/{name}.sql`** — {h['business_question']}")
                st.caption(f"Grain: {h['grain']} · Techniques: {h['techniques']}")
            else:
                st.markdown(f"**`{name}`**")
        if applied:
            st.caption("Filters applied: " + ", ".join(applied))
        if skipped:
            st.caption(
                "Not filterable here (the query's grain has no such column): " + ", ".join(skipped)
            )
        if note:
            st.caption(note)
        if table_view is not None:
            st.dataframe(table_view, width="stretch", hide_index=True)


def footer() -> None:
    st.markdown(
        '<div class="sg-footer">Synthetic data — portfolio project · StayGuard</div>',
        unsafe_allow_html=True,
    )
