"""Plotly figure builders for the analytics tabs.

Pure plotly (no Qt), so the figures can be unit-tested without a QApplication
and later reused for the PDF memo. Each builder takes a result dataclass and
returns a :class:`plotly.graph_objects.Figure`; empty or absent results yield a
figure with a friendly placeholder annotation rather than raising.
"""

from __future__ import annotations

import math

import plotly.graph_objects as go

from duw.domain.results import (
    CollateralResult,
    CVAResult,
    ExposureProfile,
    LimitCheck,
)

# A small consistent palette used across the tabs.
_EE = "#1f77b4"
_PFE95 = "#ff7f0e"
_PFE99 = "#d62728"
_COLLAT = "#2ca02c"
_UNCOLLAT = "#7f7f7f"
_BREACH = "#d62728"
_OK = "#2ca02c"


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
                font=dict(size=14, color="#888"),
            )
        ],
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
    )
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
    fig.add_trace(
        go.Bar(
            x=[max(limits.current_peak_pfe, 0.0)],
            y=["Peak PFE"],
            orientation="h",
            name="Existing",
            marker_color=_UNCOLLAT,
        )
    )
    fig.add_trace(
        go.Bar(
            x=[max(limits.incremental_peak_pfe, 0.0)],
            y=["Peak PFE"],
            orientation="h",
            name="Incremental (proposed)",
            marker_color=color,
        )
    )
    if not math.isnan(limits.limit):
        fig.add_vline(
            x=limits.limit,
            line=dict(color="#111", width=2, dash="dash"),
            annotation_text=f"Limit {limits.limit:,.0f}",
            annotation_position="top",
        )
    fig.update_layout(
        barmode="stack",
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
        margin=dict(l=90, r=40, t=54, b=80),
        legend=dict(orientation="h", yanchor="top", y=-0.25, x=0.5, xanchor="center"),
        xaxis_title="Exposure",
    )
    return fig
