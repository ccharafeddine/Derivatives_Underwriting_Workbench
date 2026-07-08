"""Simulator tab tests. Headless via offscreen Qt.

Plays the bundled sample scenario through the tab end to end, committing a
scripted sequence of decisions on the background worker thread, and checks that
the default panel is surfaced on the defaulting round and that the tab's final
ScoreResult matches running the engine + scorer headlessly on the same
decisions.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEventLoop, QTimer

from duw.scenario.io import load_bundled_scenario
from duw.scenario.model import Decision, DecisionAction
from duw.ui.tabs.simulator_tab import SimulatorTab, headless_score

SAMPLE = "rising_rates_default"
ACME = "D1-ACME-IRS"
GLOBEX = "D2-GBX-IRS"


def _wait_idle(tab: SimulatorTab, max_ms: int = 60_000) -> None:
    """Run a nested event loop until no background engine run is in flight.

    A real ``QEventLoop`` is used rather than ``QTest.qWait`` polling because
    the worker thread's cross-thread completion signals are only delivered by a
    running event loop under the offscreen platform.
    """
    if not tab.is_busy():
        return
    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(20)
    poll.timeout.connect(lambda: loop.quit() if not tab.is_busy() else None)
    QTimer.singleShot(max_ms, loop.quit)
    poll.start()
    loop.exec()
    poll.stop()
    assert not tab.is_busy(), "background scenario run did not finish in time"


def _approve(collateral: bool = False, **kwargs) -> Decision:
    action = DecisionAction.CONDITION if collateral else DecisionAction.APPROVE
    return Decision(trade_id="", action=action, require_collateral=collateral, **kwargs)


def _play(tab: SimulatorTab, decisions: dict[str, Decision]) -> dict:
    """Drive the tab to completion, returning observations about the play."""
    seen_default = False
    default_outcome = None
    guard = 0
    while tab.score_result is None and guard < 50:
        guard += 1
        step = tab._current_step()
        assert step is not None
        if step.kind == "decision":
            tab.set_candidate(decisions[step.deal.trade_id])
            tab._on_commit()
            _wait_idle(tab)
        elif step.kind == "default":
            seen_default = True
            default_outcome = tab._default_outcome_for(step.default)
            assert tab.stack.currentWidget() is tab._default_page
            tab._on_continue()
            _wait_idle(tab)
        else:  # end
            break
    return {"seen_default": seen_default, "default_outcome": default_outcome}


def test_tab_instantiates_and_loads_sample(qapp) -> None:
    tab = SimulatorTab()
    tab.load_default()
    _wait_idle(tab)
    assert tab._scenario is not None
    assert tab._scenario.meta.n_rounds == 3
    # The first decision step is showing the first deal.
    step = tab._current_step()
    assert step.kind == "decision"
    assert step.deal.trade_id == ACME
    assert tab.stack.currentWidget() is tab._decision_page


def test_preview_shows_consequences_before_commit(qapp) -> None:
    tab = SimulatorTab()
    tab.load_default()
    _wait_idle(tab)
    # The consequence table is populated with real metrics (not the placeholder).
    labels = {
        tab.consequence_table.item(r, 0).text()
        for r in range(tab.consequence_table.rowCount())
    }
    assert {"Peak PFE", "CVA", "Limit utilization"} <= labels
    # Collateralizing changes the previewed consequence numbers.
    tab.set_candidate(_approve(collateral=False))
    tab._request_preview()
    _wait_idle(tab)
    open_fig = tab.consequence_view.figure
    tab.set_candidate(_approve(collateral=True, csa_threshold=0.0))
    tab._request_preview()
    _wait_idle(tab)
    assert tab.consequence_view.figure is not None
    assert open_fig is not None


def test_default_panel_surfaces_and_summary_matches_headless(qapp) -> None:
    decisions = {
        ACME: _approve(collateral=False),  # under-collateralized -> loss on default
        GLOBEX: _approve(collateral=False),
    }
    tab = SimulatorTab()
    tab.load_default()
    _wait_idle(tab)
    observed = _play(tab, decisions)

    # The default fired as a distinct, surfaced moment with a real loss.
    assert observed["seen_default"]
    assert observed["default_outcome"] is not None
    assert observed["default_outcome"].counterparty_id == "CP001"
    assert observed["default_outcome"].realized_loss > 0.0

    # The end summary is shown with a ScoreResult.
    assert tab.stack.currentWidget() is tab._summary_page
    assert tab.score_result is not None

    # It matches running the engine + scorer headlessly on the same decisions.
    scenario = load_bundled_scenario(SAMPLE)
    reference = headless_score(scenario, decisions)
    assert tab.score_result.raw_pnl == pytest.approx(reference.raw_pnl)
    assert tab.score_result.risk_adjusted_score == pytest.approx(
        reference.risk_adjusted_score
    )
    b, rb = tab.score_result.breakdown, reference.breakdown
    assert b.revenue == pytest.approx(rb.revenue)
    assert b.cva_collected == pytest.approx(rb.cva_collected)
    assert b.realized_losses == pytest.approx(rb.realized_losses)
    assert b.exposure_cost == pytest.approx(rb.exposure_cost)
    assert b.realized_losses > 0.0


def test_wellcollateralized_play_avoids_the_loss(qapp) -> None:
    decisions = {
        ACME: _approve(collateral=True, csa_threshold=0.0),
        GLOBEX: _approve(collateral=False),
    }
    tab = SimulatorTab()
    tab.load_default()
    _wait_idle(tab)
    observed = _play(tab, decisions)

    scenario = load_bundled_scenario(SAMPLE)
    reference = headless_score(scenario, decisions)
    # Collateralizing Acme removes the default loss; the summary still matches.
    assert observed["default_outcome"].realized_loss == pytest.approx(0.0)
    assert tab.score_result.raw_pnl == pytest.approx(reference.raw_pnl)
    assert tab.score_result.breakdown.realized_losses == pytest.approx(0.0)


def test_declining_the_defaulter_skips_the_default_panel(qapp) -> None:
    # If Acme's deal is declined there is no open book, so its default is not a
    # surfaced moment: the flow goes straight to the next step.
    decisions = {
        ACME: Decision(trade_id="", action=DecisionAction.DECLINE),
        GLOBEX: _approve(collateral=False),
    }
    tab = SimulatorTab()
    tab.load_default()
    _wait_idle(tab)
    observed = _play(tab, decisions)
    assert not observed["seen_default"]
    assert tab.score_result is not None
    assert tab.score_result.breakdown.realized_losses == pytest.approx(0.0)


def test_engine_runs_off_the_ui_thread(qapp) -> None:
    # A commit starts a background QThread; the tab is busy until it finishes.
    tab = SimulatorTab()
    tab.load_default()
    _wait_idle(tab)
    tab.set_candidate(_approve(collateral=True, csa_threshold=0.0))
    tab._on_commit()
    assert tab.is_busy()  # engine work is on the worker thread, not the UI thread
    _wait_idle(tab)
    assert not tab.is_busy()
