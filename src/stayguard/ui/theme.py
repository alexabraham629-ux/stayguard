"""Colours and the Plotly template. Values from the validated reference palette (dataviz skill):
categorical slots in fixed order, one blue accent, status red reserved for "at risk"."""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

SURFACE = "#fcfcfb"
PAGE = "#f9f9f7"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
NEUTRAL = "#c3c2b7"  # de-emphasised marks
ACCENT = "#2a78d6"  # categorical slot 1, the single accent
CATEGORICAL = [
    "#2a78d6",
    "#eb6834",
    "#1baf7a",
    "#eda100",
    "#e87ba4",
    "#008300",
    "#6250d6",
    "#e34948",
]
CRITICAL = "#d03b3b"  # status: at risk / lost
GOOD = "#0ca30c"
DIVERGING_NEG = "#e34948"
DIVERGING_POS = "#2a78d6"
SEQUENTIAL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

TEMPLATE_NAME = "stayguard"


def register_template() -> None:
    """Register and default the StayGuard Plotly template (idempotent)."""
    axis = dict(
        gridcolor=GRID,
        linecolor=AXIS,
        zerolinecolor=AXIS,
        tickfont=dict(color=MUTED, size=12),
        title=dict(font=dict(color=INK_SECONDARY, size=12)),
        ticks="",
        automargin=True,
    )
    pio.templates[TEMPLATE_NAME] = go.layout.Template(
        layout=dict(
            font=dict(family=FONT, color=INK, size=13),
            paper_bgcolor=SURFACE,
            plot_bgcolor=SURFACE,
            colorway=CATEGORICAL,
            xaxis=dict(axis, showgrid=False),
            yaxis=dict(axis, showgrid=True),
            margin=dict(l=8, r=8, t=48, b=8),
            legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, title=None),
            hoverlabel=dict(bgcolor="white", bordercolor=GRID, font=dict(color=INK, family=FONT)),
            barcornerradius=4,
            bargap=0.3,
        )
    )
    pio.templates.default = TEMPLATE_NAME


def intake_colors(intakes: list[str]) -> dict[str, str]:
    """Colour follows the intake (entity), never its rank, so filters never repaint a series."""
    return {intake: CATEGORICAL[i % len(CATEGORICAL)] for i, intake in enumerate(intakes)}
