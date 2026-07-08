"""Interpretation engine and memo/report tests (Session 10). Qt-free."""

from __future__ import annotations

from datetime import date

from duw.domain.counterparty import Counterparty, CreditProfile, Financials
from duw.domain.instruments import IRS, NettingSet, SwapDirection
from duw.domain.market import MarketSnapshot
from duw.domain.results import (
    AnalysisResults,
    CollateralResult,
    CVAResult,
    ExposureProfile,
    LimitCheck,
)
from duw.reports.deck import write_memo_pptx
from duw.reports.interpreter import (
    DISCLAIMER,
    recommend,
    section_commentary,
)
from duw.reports.memo import SECTIONS, generate_memo, render_memo_html, write_memo_pdf

AS_OF = date(2025, 6, 30)
GRID = (0.0, 1.0, 2.0, 3.0)


def _financials() -> Financials:
    return Financials(
        total_assets=5000.0,
        total_liabilities=2000.0,
        current_assets=2500.0,
        current_liabilities=1000.0,
        retained_earnings=1500.0,
        ebit=800.0,
        sales=6000.0,
        market_equity=4000.0,
        equity_volatility=0.25,
    )


def _results(
    *, breach: bool = False, grade: str = "A", zone: str = "safe"
) -> AnalysisResults:
    trade = IRS(
        trade_id="T1",
        counterparty_id="CP001",
        notional=10_000_000.0,
        currency="USD",
        trade_date=AS_OF,
        maturity_date=date(2030, 6, 30),
        fixed_rate=0.043,
        direction=SwapDirection.PAY_FIXED,
    )
    return AnalysisResults(
        snapshot=MarketSnapshot(as_of=AS_OF),
        counterparty=Counterparty(
            counterparty_id="CP001",
            name="Acme Corp",
            sector="Industrials",
            financials=_financials(),
        ),
        netting_set=NettingSet("NS", "CP001", (trade,)),
        credit_profile=CreditProfile(
            counterparty_id="CP001",
            merton_pd=0.005,
            altman_z=3.4,
            altman_zone=zone,
            internal_grade=grade,
            distance_to_default=2.6,
            pd_term_structure=((1.0, 0.005), (5.0, 0.03)),
        ),
        exposure=ExposureProfile(
            time_grid=GRID,
            ee=(0.0, 100.0, 150.0, 50.0),
            epe=90.0,
            pfe_95=(0.0, 300.0, 400.0, 120.0),
            pfe_99=(0.0, 450.0, 600.0, 180.0),
            peak_pfe=400.0,
            peak_pfe_time=2.0,
        ),
        collateral=CollateralResult(
            threshold=250_000.0,
            initial_margin=0.0,
            mpor_days=10,
            time_grid=GRID,
            ee_uncollateralized=(0.0, 100.0, 150.0, 50.0),
            ee_collateralized=(0.0, 40.0, 60.0, 20.0),
            peak_pfe_uncollateralized=400.0,
            peak_pfe_collateralized=120.0,
        ),
        cva=CVAResult(
            cva=5000.0,
            dva=2000.0,
            bcva=3000.0,
            lgd=0.6,
            time_grid=GRID,
            contributions=(0.0, 1500.0, 2500.0, 1000.0),
        ),
        limits=LimitCheck(
            limit=1_000_000.0,
            current_peak_pfe=0.0,
            proposed_peak_pfe=400_000.0,
            incremental_peak_pfe=400_000.0,
            utilization=1.4 if breach else 0.4,
            headroom=-400_000.0 if breach else 600_000.0,
            breach=breach,
        ),
    )


# --------------------------------------------------------------------------- #
# Interpreter
# --------------------------------------------------------------------------- #
def test_section_commentary_is_populated() -> None:
    commentary = section_commentary(_results())
    assert set(commentary) == {
        "counterparty",
        "exposure",
        "collateral",
        "cva",
        "limits",
    }
    for text in commentary.values():
        assert isinstance(text, str) and len(text) > 20
    assert "Acme Corp" in commentary["counterparty"]


def test_recommend_approves_clean_run() -> None:
    rec = recommend(_results(grade="A", zone="safe", breach=False))
    assert rec.verdict == "Approve"
    assert rec.rationale.endswith(".")


def test_recommend_declines_on_breach() -> None:
    rec = recommend(_results(breach=True))
    assert rec.verdict == "Decline"
    assert "breach" in rec.rationale.lower()


def test_recommend_declines_distressed_counterparty() -> None:
    rec = recommend(_results(grade="CCC", zone="distress"))
    assert rec.verdict == "Decline"


# --------------------------------------------------------------------------- #
# Memo HTML / PDF
# --------------------------------------------------------------------------- #
def test_memo_html_contains_all_sections_and_disclaimer() -> None:
    html = render_memo_html(_results(), include_charts=False)
    for section in SECTIONS:
        assert section in html
    assert DISCLAIMER in html
    assert "Acme Corp" in html
    assert "Approve" in html


def test_generate_memo_writes_html_and_pdf(tmp_path) -> None:
    result = generate_memo(
        _results(), tmp_path, formats=("html", "pdf"), include_charts=False
    )
    html = tmp_path / "underwriting_memo.html"
    pdf = tmp_path / "underwriting_memo.pdf"
    assert html.exists() and pdf.exists()
    assert result.html_path == str(html)
    assert result.pdf_path == str(pdf)
    assert result.recommendation == "Approve"
    # The PDF is a real PDF file.
    assert pdf.read_bytes().startswith(b"%PDF")


def test_memo_pdf_written_directly(tmp_path) -> None:
    path = write_memo_pdf(_results(), tmp_path / "memo.pdf", include_charts=False)
    assert path.exists()
    assert path.read_bytes().startswith(b"%PDF")


def test_deck_pptx_is_written(tmp_path) -> None:
    path = write_memo_pptx(_results(), tmp_path / "deck.pptx")
    assert path.exists()
    assert path.stat().st_size > 0
