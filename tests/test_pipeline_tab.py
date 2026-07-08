"""Deal pipeline tab tests (Session 11). Headless via offscreen Qt."""

from __future__ import annotations

from datetime import date

from duw.domain.counterparty import Counterparty
from duw.domain.instruments import IRS, NettingSet, SwapDirection
from duw.domain.results import AnalysisResults, ExposureProfile, MemoResult
from duw.store.deals import Deal, DealStage, DealStore
from duw.ui.tabs.pipeline_tab import PipelineTab

AS_OF = date(2025, 6, 30)


def _results(name: str = "Acme Corp") -> AnalysisResults:
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
        run_config={"seed": 2024, "n_paths": 400, "n_steps": 5},
        counterparty=Counterparty("CP001", name, "Industrials"),
        netting_set=NettingSet("NS", "CP001", (trade,)),
        exposure=ExposureProfile(peak_pfe=400_000.0, peak_pfe_time=2.0),
        memo=MemoResult(recommendation="Approve"),
    )


def _store(tmp_path) -> DealStore:
    return DealStore(tmp_path / "deals.json")


def test_pipeline_tab_groups_deals_by_stage(qapp, tmp_path) -> None:
    store = _store(tmp_path)
    store.save(Deal.from_results("Deal A", _results(), deal_id="d1"))
    store.save(
        Deal.from_results("Deal B", _results(), stage=DealStage.EXECUTED, deal_id="d2")
    )
    tab = PipelineTab(store)
    assert tab._columns[DealStage.REQUESTED.value].count() == 1
    assert tab._columns[DealStage.EXECUTED.value].count() == 1
    assert tab._columns[DealStage.DOCUMENTED.value].count() == 0


def test_pipeline_tab_move_updates_stage(qapp, tmp_path) -> None:
    store = _store(tmp_path)
    store.save(Deal.from_results("Deal A", _results(), deal_id="d1"))
    tab = PipelineTab(store)
    requested = tab._columns[DealStage.REQUESTED.value]
    requested.setCurrentRow(0)
    tab._move(+1)  # advance to the next stage
    assert store.get("d1").stage is DealStage.UNDER_REVIEW
    assert tab._columns[DealStage.UNDER_REVIEW.value].count() == 1
    assert tab._columns[DealStage.REQUESTED.value].count() == 0


def test_pipeline_tab_reopen_emits_deal(qapp, tmp_path) -> None:
    store = _store(tmp_path)
    store.save(Deal.from_results("Deal A", _results(), deal_id="d1"))
    tab = PipelineTab(store)
    captured: list = []
    tab.reopenRequested.connect(captured.append)
    tab._columns[DealStage.REQUESTED.value].setCurrentRow(0)
    tab._reopen()
    assert len(captured) == 1
    assert captured[0].deal_id == "d1"


def test_pipeline_tab_delete(qapp, tmp_path) -> None:
    store = _store(tmp_path)
    store.save(Deal.from_results("Deal A", _results(), deal_id="d1"))
    tab = PipelineTab(store)
    tab._columns[DealStage.REQUESTED.value].setCurrentRow(0)
    tab._delete()
    assert store.get("d1") is None
    assert tab._columns[DealStage.REQUESTED.value].count() == 0


def test_main_window_save_deal_and_reopen(qapp, tmp_path) -> None:
    from duw.ui.main_window import MainWindow

    store = _store(tmp_path)
    window = MainWindow(store=store)
    # Simulate a completed run and save it as a deal.
    window._on_finished(_results())
    assert window.save_deal_action.isEnabled()
    deal = Deal.from_results("Saved run", window.results)
    window.pipeline_tab.add_deal(deal)
    assert len(store.list()) == 1
    # Reopening reconstructs inputs without raising (no thread already running).
    assert window._thread is None
    reopened = store.list()[0]
    cp, existing, proposed, config = reopened.to_run_inputs()
    assert cp.name == "Acme Corp"
    assert config.seed == 2024
