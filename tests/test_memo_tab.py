"""Memo tab tests (Session 10). Headless via offscreen Qt."""

from __future__ import annotations

from datetime import date

from duw.domain.counterparty import Counterparty, CreditProfile
from duw.domain.instruments import IRS, NettingSet, SwapDirection
from duw.domain.market import MarketSnapshot
from duw.domain.results import AnalysisResults, CVAResult, ExposureProfile, LimitCheck
from duw.reports.memo import SECTIONS
from duw.ui.tabs.memo_tab import MemoTab

AS_OF = date(2025, 6, 30)
GRID = (0.0, 1.0, 2.0, 3.0)


def _results() -> AnalysisResults:
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
        counterparty=Counterparty("CP001", "Acme Corp", "Industrials"),
        netting_set=NettingSet("NS", "CP001", (trade,)),
        credit_profile=CreditProfile(counterparty_id="CP001", internal_grade="A"),
        exposure=ExposureProfile(
            time_grid=GRID,
            ee=(0.0, 100.0, 150.0, 50.0),
            epe=90.0,
            pfe_95=(0.0, 300.0, 400.0, 120.0),
            pfe_99=(0.0, 450.0, 600.0, 180.0),
            peak_pfe=400.0,
            peak_pfe_time=2.0,
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
            utilization=0.4,
            headroom=600_000.0,
            breach=False,
        ),
    )


def test_memo_tab_previews_and_enables_export(qapp) -> None:
    tab = MemoTab()
    assert not tab.export_pdf_btn.isEnabled()
    tab.set_results(_results())
    assert tab.export_pdf_btn.isEnabled()
    for section in SECTIONS:
        assert section in tab.preview_html
    assert "Acme Corp" in tab.preview_html


def test_memo_tab_export_html_writes_file(qapp, tmp_path) -> None:
    from duw.reports.memo import write_memo_html

    tab = MemoTab()
    tab.set_results(_results())
    out = tmp_path / "memo.html"
    # Exercise the export writer directly (bypassing the file dialog).
    tab._export(lambda p: write_memo_html(tab.results, p), str(out))
    assert out.exists()
    assert "Recommendation" in out.read_text(encoding="utf-8")
