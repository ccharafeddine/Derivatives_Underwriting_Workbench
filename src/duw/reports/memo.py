"""Underwriting memo.

Assembles a one-page underwriting memo from an :class:`AnalysisResults` and
exports it as self-contained HTML and a reportlab PDF. The HTML embeds
interactive plotly charts with plotly.js inlined (no network, no kaleido); the
PDF embeds static PNG charts via kaleido when available and degrades to a
text-only memo otherwise.

Every export carries the full disclaimer and presents the recommendation as
illustrative, never as real credit advice. Pure Python; no Qt.
"""

from __future__ import annotations

import math
from datetime import date
from io import BytesIO
from pathlib import Path

from duw.domain.instruments import CDS, IRS, FXForward, Trade
from duw.domain.results import AnalysisResults, MemoResult
from duw.reports.interpreter import (
    DISCLAIMER,
    interpret_collateral,
    interpret_counterparty,
    interpret_cva,
    interpret_exposure,
    interpret_limits,
    recommend,
)

TITLE = "Counterparty Credit Underwriting Memo"

# Section headings, in order. Also used by tests to assert completeness.
SECTIONS: tuple[str, ...] = (
    "Trade Summary",
    "Counterparty",
    "Exposure",
    "Collateral",
    "CVA",
    "Limit Impact",
    "Recommendation",
    "Disclaimer",
)


def _m(x: float | None) -> str:
    return (
        "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:,.0f}"
    )


# --------------------------------------------------------------------------- #
# Row builders (shared by HTML and PDF)
# --------------------------------------------------------------------------- #
def _proposed_trade(results: AnalysisResults) -> Trade | None:
    ns = results.netting_set
    if ns is None or not ns.trades:
        return None
    return ns.trades[-1]


def _trade_rows(results: AnalysisResults) -> list[tuple[str, str]]:
    trade = _proposed_trade(results)
    if trade is None:
        return [("Trade", "none")]
    rows = [
        ("Product", trade.product),
        ("Trade ID", trade.trade_id),
        ("Notional", f"{trade.notional:,.0f} {trade.currency}"),
        ("Tenor", f"{trade.tenor_years:.2f}y"),
        ("Maturity", trade.maturity_date.isoformat()),
    ]
    if isinstance(trade, IRS):
        rows.append(("Terms", f"{trade.direction.value}, fixed {trade.fixed_rate:.3%}"))
    elif isinstance(trade, FXForward):
        rows.append(
            (
                "Terms",
                f"{trade.direction.value} {trade.base_currency}/"
                f"{trade.quote_currency} @ {trade.contract_rate:.4f}",
            )
        )
    elif isinstance(trade, CDS):
        rows.append(
            (
                "Terms",
                f"{trade.direction.value} on {trade.reference_entity}, "
                f"{trade.spread * 1e4:.0f} bps",
            )
        )
    return rows


def _counterparty_rows(results: AnalysisResults) -> list[tuple[str, str]]:
    cp = results.counterparty
    profile = results.credit_profile
    rows: list[tuple[str, str]] = []
    if cp is not None:
        rows.append(("Name", cp.name))
        rows.append(("Sector", cp.sector))
    if profile is not None:
        rows.append(("Internal grade", str(profile.internal_grade)))
        if profile.altman_z is not None:
            rows.append(("Altman Z", f"{profile.altman_z:.2f} ({profile.altman_zone})"))
        if profile.merton_pd is not None:
            rows.append(("Merton 1y PD", f"{profile.merton_pd:.2%}"))
    return rows or [("Counterparty", "n/a")]


def _exposure_rows(results: AnalysisResults) -> list[tuple[str, str]]:
    exp = results.exposure
    if exp is None:
        return [("Exposure", "n/a")]
    return [
        ("EPE", _m(exp.epe)),
        ("Peak PFE (95%)", _m(exp.peak_pfe)),
        ("Peak PFE time", f"{exp.peak_pfe_time:.2f}y"),
    ]


def _collateral_rows(results: AnalysisResults) -> list[tuple[str, str]]:
    col = results.collateral
    if col is None:
        return [("Collateral", "n/a")]
    return [
        ("Peak PFE uncollateralized", _m(col.peak_pfe_uncollateralized)),
        ("Peak PFE collateralized", _m(col.peak_pfe_collateralized)),
        ("MPoR (days)", str(col.mpor_days)),
    ]


def _cva_rows(results: AnalysisResults) -> list[tuple[str, str]]:
    cva = results.cva
    if cva is None:
        return [("CVA", "n/a")]
    rows = [
        ("CVA", _m(cva.cva)),
        ("DVA", _m(cva.dva)),
        ("BCVA", _m(cva.bcva)),
        ("FVA", _m(cva.fva)),
    ]
    if cva.wwr_correlation:
        rows.append(("Wrong-way corr.", f"{cva.wwr_correlation:+.2f}"))
    return rows


def _limit_rows(results: AnalysisResults) -> list[tuple[str, str]]:
    lim = results.limits
    if lim is None:
        return [("Limit", "n/a")]
    return [
        ("Limit", _m(lim.limit)),
        ("Proposed peak PFE", _m(lim.proposed_peak_pfe)),
        ("Utilization", f"{lim.utilization:.0%}"),
        ("Breach", "YES" if lim.breach else "no"),
    ]


# --------------------------------------------------------------------------- #
# Charts
# --------------------------------------------------------------------------- #
def _figures(results: AnalysisResults) -> list[tuple[str, object]]:
    from duw.ui.widgets.charts import (
        collateral_figure,
        cva_figure,
        exposure_figure,
        limits_figure,
    )

    return [
        ("Exposure", exposure_figure(results.exposure)),
        ("Collateral", collateral_figure(results.collateral)),
        ("CVA", cva_figure(results.cva)),
        ("Limits", limits_figure(results.limits)),
    ]


def _figure_png(figure: object) -> bytes | None:
    """Render a plotly figure to PNG bytes, or ``None`` if kaleido is absent."""
    try:
        return figure.to_image(format="png", width=760, height=380)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# HTML
# --------------------------------------------------------------------------- #
def render_memo_html(results: AnalysisResults, include_charts: bool = True) -> str:
    """Render the memo as a self-contained HTML document."""
    rec = recommend(results)
    as_of = results.snapshot.as_of if results.snapshot is not None else date.today()

    def table(rows: list[tuple[str, str]]) -> str:
        cells = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows)
        return f"<table class='kv'>{cells}</table>"

    chart_html = ""
    plotly_js = ""
    if include_charts:
        from plotly.io import to_html
        from plotly.offline import get_plotlyjs

        plotly_js = f"<script>{get_plotlyjs()}</script>"
        divs = []
        for _name, fig in _figures(results):
            divs.append(to_html(fig, include_plotlyjs=False, full_html=False))
        chart_html = "<div class='charts'>" + "".join(divs) + "</div>"

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{TITLE}</title>
<style>
 body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 2em;
        color: #1a1a1a; max-width: 900px; }}
 h1 {{ font-size: 1.5em; margin-bottom: 0.2em; }}
 h2 {{ font-size: 1.1em; border-bottom: 1px solid #ddd; padding-bottom: 3px;
       margin-top: 1.4em; }}
 .meta {{ color: #666; font-size: 0.9em; }}
 table.kv {{ border-collapse: collapse; margin: 0.4em 0; }}
 table.kv th {{ text-align: left; padding: 2px 14px 2px 0; color: #555;
                font-weight: 600; }}
 table.kv td {{ padding: 2px 0; }}
 .rec {{ background:#eef4fb; border-left: 4px solid #1f77b4; padding: 10px 14px;
         margin: 0.6em 0; }}
 .rec .verdict {{ font-weight: 700; font-size: 1.1em; }}
 .disclaimer {{ color:#777; font-size:0.8em; border-top:1px solid #ddd;
                margin-top:1.6em; padding-top:0.6em; }}
 .charts > div {{ margin: 0.8em 0; }}
</style></head><body>
<h1>{TITLE}</h1>
<div class="meta">Market as of {as_of.isoformat()} · educational portfolio model</div>

<h2>Trade Summary</h2>
{table(_trade_rows(results))}

<h2>Counterparty</h2>
{table(_counterparty_rows(results))}
<p>{interpret_counterparty(results)}</p>

<h2>Exposure</h2>
{table(_exposure_rows(results))}
<p>{interpret_exposure(results)}</p>

<h2>Collateral</h2>
{table(_collateral_rows(results))}
<p>{interpret_collateral(results)}</p>

<h2>CVA</h2>
{table(_cva_rows(results))}
<p>{interpret_cva(results)}</p>

<h2>Limit Impact</h2>
{table(_limit_rows(results))}
<p>{interpret_limits(results)}</p>

<h2>Recommendation</h2>
<div class="rec"><span class="verdict">{rec.verdict}</span><br>{rec.rationale}</div>

{chart_html}

<div class="disclaimer"><b>Disclaimer.</b> {DISCLAIMER}</div>
{plotly_js}
</body></html>"""


def write_memo_html(
    results: AnalysisResults, path: str | Path, include_charts: bool = True
) -> Path:
    """Write the HTML memo to ``path``."""
    out = Path(path)
    out.write_text(render_memo_html(results, include_charts), encoding="utf-8")
    return out


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #
def write_memo_pdf(
    results: AnalysisResults, path: str | Path, include_charts: bool = True
) -> Path:
    """Write the PDF memo to ``path`` using reportlab."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Image,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    out = Path(path)
    styles = getSampleStyleSheet()
    small = ParagraphStyle(
        "small", parent=styles["Normal"], fontSize=8, textColor=colors.grey
    )
    rec = recommend(results)

    def kv_table(rows: list[tuple[str, str]]) -> Table:
        t = Table([[k, v] for k, v in rows], colWidths=[2.2 * inch, 4.0 * inch])
        t.setStyle(
            TableStyle(
                [
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555555")),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        return t

    story: list = [
        Paragraph(TITLE, styles["Title"]),
        Paragraph("Educational portfolio model — not credit advice", small),
        Spacer(1, 10),
    ]

    def section(heading: str, rows: list[tuple[str, str]], prose: str) -> None:
        story.append(Paragraph(heading, styles["Heading2"]))
        story.append(kv_table(rows))
        story.append(Paragraph(prose, styles["Normal"]))
        story.append(Spacer(1, 8))

    story.append(Paragraph("Trade Summary", styles["Heading2"]))
    story.append(kv_table(_trade_rows(results)))
    story.append(Spacer(1, 8))
    section(
        "Counterparty", _counterparty_rows(results), interpret_counterparty(results)
    )
    section("Exposure", _exposure_rows(results), interpret_exposure(results))
    section("Collateral", _collateral_rows(results), interpret_collateral(results))
    section("CVA", _cva_rows(results), interpret_cva(results))
    section("Limit Impact", _limit_rows(results), interpret_limits(results))

    story.append(Paragraph("Recommendation", styles["Heading2"]))
    story.append(Paragraph(f"<b>{rec.verdict}.</b> {rec.rationale}", styles["Normal"]))
    story.append(Spacer(1, 10))

    if include_charts:
        for _name, fig in _figures(results):
            png = _figure_png(fig)
            if png is not None:
                story.append(Image(BytesIO(png), width=5.6 * inch, height=2.8 * inch))
                story.append(Spacer(1, 6))

    story.append(Spacer(1, 10))
    story.append(Paragraph(f"<b>Disclaimer.</b> {DISCLAIMER}", small))

    doc = SimpleDocTemplate(str(out), pagesize=LETTER)
    doc.build(story)
    return out


# --------------------------------------------------------------------------- #
# Orchestration entry point
# --------------------------------------------------------------------------- #
def generate_memo(
    results: AnalysisResults,
    output_dir: str | Path,
    *,
    formats: tuple[str, ...] = ("html", "pdf"),
    include_charts: bool = True,
    basename: str = "underwriting_memo",
) -> MemoResult:
    """Generate the requested memo formats into ``output_dir``."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    rec = recommend(results)
    html_path = pdf_path = pptx_path = None

    if "html" in formats:
        html_path = str(
            write_memo_html(results, out / f"{basename}.html", include_charts)
        )
    if "pdf" in formats:
        pdf_path = str(write_memo_pdf(results, out / f"{basename}.pdf", include_charts))
    if "pptx" in formats:
        from duw.reports.deck import write_memo_pptx

        pptx_path = str(write_memo_pptx(results, out / f"{basename}.pptx"))

    return MemoResult(
        html_path=html_path,
        pdf_path=pdf_path,
        pptx_path=pptx_path,
        recommendation=rec.verdict,
    )
