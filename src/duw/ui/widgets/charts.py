"""Plotly figure builders for the analytics tabs.

Pure plotly (no Qt), so the figures can be unit-tested without a QApplication
and later reused for the PDF memo. Each builder takes a result dataclass and
returns a :class:`plotly.graph_objects.Figure`; empty or absent results yield a
figure with a friendly placeholder annotation rather than raising.
"""

from __future__ import annotations

import math

import plotly.graph_objects as go

from duw.domain.market import MarketSnapshot
from duw.domain.results import (
    CollateralResult,
    CVAResult,
    ExposureProfile,
    LimitCheck,
)

# A qualitative color cycle for overlaying several curves (currencies / issuers).
_SERIES = ("#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b")

# A small consistent palette used across the tabs. These series colors read on
# both a light and a dark background; the background, grid, text, and reference
# lines are what change with the theme (see ``apply_chart_theme``).
_EE = "#1f77b4"
_PFE95 = "#ff7f0e"
_PFE99 = "#d62728"
_COLLAT = "#2ca02c"
_UNCOLLAT = "#7f7f7f"
_BREACH = "#d62728"
_OK = "#2ca02c"

# The neutral color the reference lines (limit lines) are drawn with; recolored
# per theme by ``apply_chart_theme`` so they stay visible on a dark ground.
_REF_LINE = "#111111"
# The muted grey used for placeholder text; recolored per theme.
_PLACEHOLDER = "#888888"

# Per-theme chart chrome: page/plot background, text, grid, and reference lines.
_CHART_THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "template": "plotly_dark",
        "paper": "#0e0f12",
        "plot": "#0e0f12",
        "font": "#d2cbb9",
        "grid": "#23262c",
        "zero": "#2f333b",
        "ref": "#ffab33",
        "muted": "#9a927f",
    },
    "light": {
        "template": "plotly_white",
        "paper": "#efe8d8",
        "plot": "#f5efe2",
        "font": "#2a2419",
        "grid": "#d5cbb4",
        "zero": "#c4b89e",
        "ref": "#2a2419",
        "muted": "#6b5f49",
    },
}


def chart_palette(theme: str) -> dict[str, str]:
    """Return the chart chrome colors for ``theme`` ("dark" or "light")."""
    return _CHART_THEMES.get(theme, _CHART_THEMES["dark"])


# The full set of colors a reference line / muted annotation may currently hold,
# so re-theming an already-themed figure re-matches it (not just the original).
_REF_COLORS = {_REF_LINE, *(t["ref"] for t in _CHART_THEMES.values())}
_MUTED_COLORS = {_PLACEHOLDER, *(t["muted"] for t in _CHART_THEMES.values())}


def apply_chart_theme(fig: go.Figure, theme: str) -> go.Figure:
    """Restyle a figure's chrome (background, text, grid, reference lines) in place.

    The trace colors are left alone — they read on either background — but the
    paper/plot backgrounds, font, gridlines, hardcoded reference lines, and
    annotation text are recolored so the chart sits on the themed app rather than
    floating as a bright white card. Safe to call repeatedly (e.g. on each theme
    switch): reference lines and muted text are matched against every theme's
    colors, not only their original values.
    """
    t = chart_palette(theme)
    fig.update_layout(
        template=t["template"],
        paper_bgcolor=t["paper"],
        plot_bgcolor=t["plot"],
        font=dict(color=t["font"]),
    )
    fig.update_xaxes(gridcolor=t["grid"], zerolinecolor=t["zero"])
    fig.update_yaxes(gridcolor=t["grid"], zerolinecolor=t["zero"])
    # Recolor the reference lines so they do not vanish on a dark ground.
    for shape in fig.layout.shapes:
        if shape.line is not None and shape.line.color in _REF_COLORS:
            shape.line.color = t["ref"]
    # Make annotation text legible: the muted placeholder stays muted, everything
    # else (EPE / limit callouts, whose default is dark) follows the theme font.
    for ann in fig.layout.annotations:
        ann.font.color = t["muted"] if ann.font.color in _MUTED_COLORS else t["font"]
    return fig


def _base_layout(fig: go.Figure, title: str, ytitle: str = "Exposure") -> go.Figure:
    # Title sits top-left; the legend runs horizontally along the bottom so the
    # two never share the top band (which previously overlapped the title text).
    fig.update_layout(
        title=dict(
            text=title,
            x=0.02,
            xanchor="left",
            y=0.97,
            yanchor="top",
            font=dict(size=15),
        ),
        template="plotly_white",
        margin=dict(l=64, r=30, t=54, b=84),
        legend=dict(orientation="h", yanchor="top", y=-0.22, x=0.5, xanchor="center"),
        xaxis_title="Years",
        yaxis_title=ytitle,
    )
    return fig


def _placeholder(message: str) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        template="plotly_white",
        margin=dict(l=20, r=20, t=20, b=20),
        annotations=[
            dict(
                text=message,
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font=dict(size=14, color=_PLACEHOLDER),
            )
        ],
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
    )
    return fig


def yield_curves_figure(snapshot: MarketSnapshot | None) -> go.Figure:
    """Zero (discount) curves by currency: zero rate (%) against tenor."""
    if snapshot is None or not snapshot.discount_curves:
        return _placeholder("No yield curves in the market snapshot.")
    fig = go.Figure()
    for i, (ccy, curve) in enumerate(snapshot.discount_curves.items()):
        fig.add_trace(
            go.Scatter(
                x=list(curve.tenors),
                y=[r * 100.0 for r in curve.zero_rates],
                name=ccy,
                mode="lines+markers",
                line=dict(color=_SERIES[i % len(_SERIES)], width=2.5),
            )
        )
    fig = _base_layout(fig, "Zero (discount) curves", ytitle="Zero rate (%)")
    fig.update_layout(xaxis_title="Tenor (years)")
    return fig


def credit_curves_figure(snapshot: MarketSnapshot | None) -> go.Figure:
    """CDS credit-spread curves by issuer: spread (bps) against tenor."""
    if snapshot is None or not snapshot.credit_curves:
        return _placeholder("No credit-spread curves in the market snapshot.")
    fig = go.Figure()
    for i, (issuer, curve) in enumerate(snapshot.credit_curves.items()):
        fig.add_trace(
            go.Scatter(
                x=list(curve.tenors),
                y=[s * 1e4 for s in curve.spreads],
                name=issuer,
                mode="lines+markers",
                line=dict(color=_SERIES[i % len(_SERIES)], width=2.5),
            )
        )
    fig = _base_layout(fig, "Credit-spread curves", ytitle="Spread (bps)")
    fig.update_layout(xaxis_title="Tenor (years)")
    return fig


def exposure_figure(exposure: ExposureProfile | None) -> go.Figure:
    """EE / EPE line with the PFE(95) / PFE(99) cone and the peak-PFE callout."""
    if exposure is None or not exposure.time_grid:
        return _placeholder("Run an analysis to see the exposure profile.")

    x = list(exposure.time_grid)
    fig = go.Figure()
    # PFE cone: 99% as the outer band, 95% inside it.
    fig.add_trace(
        go.Scatter(
            x=x,
            y=list(exposure.pfe_99),
            name="PFE 99%",
            mode="lines",
            line=dict(color=_PFE99, width=1),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=list(exposure.pfe_95),
            name="PFE 95%",
            mode="lines",
            line=dict(color=_PFE95, width=1),
            fill="tonexty",
            fillcolor="rgba(255,127,14,0.12)",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=list(exposure.ee),
            name="EE",
            mode="lines",
            line=dict(color=_EE, width=2.5),
        )
    )
    if not math.isnan(exposure.epe):
        fig.add_hline(
            y=exposure.epe,
            line=dict(color=_EE, width=1, dash="dot"),
            annotation_text=f"EPE {exposure.epe:,.0f}",
            annotation_position="right",
        )
    if not math.isnan(exposure.peak_pfe):
        fig.add_trace(
            go.Scatter(
                x=[exposure.peak_pfe_time],
                y=[exposure.peak_pfe],
                name="Peak PFE",
                mode="markers",
                marker=dict(color=_PFE95, size=10, symbol="diamond"),
            )
        )
    return _base_layout(fig, "Exposure profile")


def collateral_figure(collateral: CollateralResult | None) -> go.Figure:
    """Uncollateralized vs collateralized expected exposure, side by side."""
    if collateral is None or not collateral.time_grid:
        return _placeholder("Run an analysis to see the collateral effect.")
    x = list(collateral.time_grid)
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=x,
            y=list(collateral.ee_uncollateralized),
            name="Uncollateralized",
            mode="lines",
            line=dict(color=_UNCOLLAT, width=2, dash="dash"),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=list(collateral.ee_collateralized),
            name="Collateralized",
            mode="lines",
            line=dict(color=_COLLAT, width=2.5),
            fill="tozeroy",
            fillcolor="rgba(44,160,44,0.10)",
        )
    )
    return _base_layout(fig, "Collateral effect on expected exposure")


def scenario_figure(
    base: ExposureProfile | None, stressed: ExposureProfile | None
) -> go.Figure:
    """Base vs stressed exposure — EE and PFE(95) overlaid."""
    if base is None or stressed is None or not base.time_grid:
        return _placeholder("Run a base analysis, then a stressed scenario.")
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=list(base.time_grid),
            y=list(base.pfe_95),
            name="Base PFE 95%",
            mode="lines",
            line=dict(color=_UNCOLLAT, width=1.5, dash="dot"),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=list(stressed.time_grid),
            y=list(stressed.pfe_95),
            name="Stressed PFE 95%",
            mode="lines",
            line=dict(color=_PFE99, width=1.5, dash="dot"),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=list(base.time_grid),
            y=list(base.ee),
            name="Base EE",
            mode="lines",
            line=dict(color=_EE, width=2.5),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=list(stressed.time_grid),
            y=list(stressed.ee),
            name="Stressed EE",
            mode="lines",
            line=dict(color=_BREACH, width=2.5),
        )
    )
    return _base_layout(fig, "Base vs stressed exposure")


def simulator_consequence_figure(
    peak_pfe: float | None,
    collateralized_peak_pfe: float | None,
    limit: float | None,
) -> go.Figure:
    """Peak PFE uncollateralized vs after collateral, against the limit.

    The consequence preview for a simulator deal: two bars (before and after the
    chosen CSA) with the credit limit as a reference line, colored red when the
    uncollateralized peak breaches the limit.
    """
    if peak_pfe is None or math.isnan(peak_pfe):
        return _placeholder("Adjust the deal to preview its exposure.")
    collat = (
        0.0 if collateralized_peak_pfe is None else max(collateralized_peak_pfe, 0.0)
    )
    breach = limit is not None and not math.isnan(limit) and peak_pfe > limit
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=["Uncollateralized", "After collateral"],
            y=[max(peak_pfe, 0.0), collat],
            marker_color=[_BREACH if breach else _UNCOLLAT, _COLLAT],
        )
    )
    if limit is not None and not math.isnan(limit):
        fig.add_hline(
            y=limit,
            line=dict(color=_REF_LINE, width=2, dash="dash"),
            annotation_text=f"Limit {limit:,.0f}",
            annotation_position="top left",
        )
    fig = _base_layout(fig, "Peak PFE vs limit", ytitle="Peak PFE (95%)")
    fig.update_layout(showlegend=False, xaxis_title="")
    return fig


def cva_figure(cva: CVAResult | None) -> go.Figure:
    """Per-interval CVA contributions over time, titled with the totals."""
    if cva is None or not cva.time_grid:
        return _placeholder("Run an analysis to see the CVA breakdown.")
    x = list(cva.time_grid)
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=x,
            y=list(cva.contributions),
            name="CVA contribution",
            marker_color=_PFE95,
        )
    )
    title = (
        f"CVA {cva.cva:,.0f} · DVA {cva.dva:,.0f} · BCVA {cva.bcva:,.0f}"
        if not math.isnan(cva.cva)
        else "CVA breakdown"
    )
    fig = _base_layout(fig, title, ytitle="Discounted expected loss")
    # Single series: the title carries the totals, so no legend is needed.
    fig.update_layout(showlegend=False)
    return fig


def limits_figure(limits: LimitCheck | None) -> go.Figure:
    """Current + incremental peak PFE against the limit, colored by breach."""
    if limits is None or math.isnan(limits.proposed_peak_pfe):
        return _placeholder("Run an analysis to see limit utilization.")
    color = _BREACH if limits.breach else _OK
    fig = go.Figure()
    # A single stacked column (existing + incremental peak PFE) against the limit
    # line — reads well whether the pane is short or tall.
    fig.add_trace(
        go.Bar(
            x=["Peak PFE"],
            y=[max(limits.current_peak_pfe, 0.0)],
            name="Existing book",
            marker_color=_UNCOLLAT,
        )
    )
    fig.add_trace(
        go.Bar(
            x=["Peak PFE"],
            y=[max(limits.incremental_peak_pfe, 0.0)],
            name="Incremental (proposed)",
            marker_color=color,
        )
    )
    if not math.isnan(limits.limit):
        fig.add_hline(
            y=limits.limit,
            line=dict(color=_REF_LINE, width=2, dash="dash"),
            annotation_text=f"Limit {limits.limit:,.0f}",
            annotation_position="top left",
        )
    fig.update_layout(
        barmode="stack",
        bargap=0.55,
        title=dict(
            text=f"Limit utilization {limits.utilization:.0%}"
            + (" — BREACH" if limits.breach else ""),
            x=0.02,
            xanchor="left",
            y=0.97,
            yanchor="top",
            font=dict(size=15),
        ),
        template="plotly_white",
        margin=dict(l=70, r=40, t=54, b=80),
        legend=dict(orientation="h", yanchor="top", y=-0.18, x=0.5, xanchor="center"),
        yaxis_title="Exposure",
        xaxis_title="",
    )
    return fig
