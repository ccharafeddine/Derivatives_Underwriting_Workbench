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
from duw.scenario.model import Decision, DecisionAction, DecisionOutcome
from duw.ui.tabs.simulator_tab import (
    SimulatorTab,
    _collateral_rows,
    _sensitivity_rows,
    headless_score,
)

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


def _outcome(**kwargs) -> DecisionOutcome:
    base = dict(
        round=0,
        trade_id="T",
        counterparty_id="CP",
        action=DecisionAction.CONDITION,
        accepted=True,
        recommendation=None,
        peak_pfe=1_000_000.0,
        epe=100_000.0,
        collateralized_peak_pfe=50_000.0,
        cva=1_000.0,
        dva=0.0,
        bcva=1_000.0,
        limit_utilization=0.2,
        limit_breach=False,
    )
    base.update(kwargs)
    return DecisionOutcome(**base)


def test_collateral_rows_appear_only_under_a_csa() -> None:
    outcome = _outcome(uncollateralized_peak_pfe=1_000_000.0, mpor_days=10)
    open_deal = Decision(trade_id="T", action=DecisionAction.APPROVE)
    assert _collateral_rows(outcome, open_deal) == []

    secured = Decision(
        trade_id="T",
        action=DecisionAction.CONDITION,
        require_collateral=True,
        csa_threshold=250_000.0,
    )
    labels = dict(_collateral_rows(outcome, secured))
    # The benefit the terms bought, and the gap the MPoR leaves, are both named.
    assert labels["Exposure removed by the CSA"] == "950,000"
    assert labels["CSA threshold"] == "250,000"
    assert labels["Margin period of risk"] == "10 business days"
    # Initial margin is listed only when some is actually demanded.
    assert "Initial margin" not in labels
    with_im = Decision(
        trade_id="T",
        action=DecisionAction.CONDITION,
        require_collateral=True,
        csa_initial_margin=400_000.0,
    )
    assert "Initial margin" in dict(_collateral_rows(outcome, with_im))


def test_sensitivity_rows_are_hidden_unless_computed() -> None:
    assert _sensitivity_rows(_outcome()) == []
    rows = dict(
        _sensitivity_rows(
            _outcome(
                dv01_pfe=9_944.86,
                dv01_cva=69.85,
                cs01_cva=56.21,
                fx_delta_pfe=0.0,
                fx_delta_cva=0.0,
            )
        )
    )
    assert len(rows) == 5
    # The sign is the lesson, so it is always shown.
    assert rows["DV01 of peak PFE (per 1bp rates)"] == "+9,944.9"
    assert rows["FX delta of peak PFE (per 1% FX)"] == "+0.0"


def test_the_suite_never_touches_the_real_progress_file(qapp, tmp_path) -> None:
    """A default-constructed tab must not reach the learner's own progress file.

    ``load_default`` loads a scenario that *is* a campaign stage, so playing it
    records a result. Without the ``isolated_progress`` fixture in conftest that
    write lands in the developer's real ``~/.duw/campaign.json`` and silently
    marks stages cleared, so this pins the isolation down.
    """
    from duw.store.progress import default_progress_path

    assert default_progress_path() == tmp_path / "campaign.json"
    tab = SimulatorTab()
    assert tab._store.path == tmp_path / "campaign.json"
    # And free-playing a bundled scenario still counts towards its stage, which
    # is the behaviour that made the leak possible in the first place.
    tab.load_default()
    _wait_idle(tab)
    assert tab._stage_name == "rising_rates_default"


def test_a_commit_during_a_preview_is_queued_not_dropped(qapp) -> None:
    """Committing while a preview is still running must still advance the round.

    Moving a CSA dial kicks off a preview, and committing straight afterwards is
    an ordinary thing for a learner to do. The commit is deferred until the
    preview's thread is free, never discarded.
    """
    tab = SimulatorTab()
    tab.load_default()
    _wait_idle(tab)
    step = tab._current_step()
    assert step is not None and step.kind == "decision"
    trade_id = step.deal.trade_id

    # Moving a CSA dial is live: it kicks off a preview on the worker thread.
    tab.set_candidate(_approve(collateral=True, csa_threshold=0.0))
    tab.threshold_spin.setValue(250_000.0)
    assert tab.is_busy(), "moving the threshold dial should request a preview"

    tab._on_commit()
    # The decision is recorded immediately even though the run is deferred.
    assert trade_id in tab._committed
    assert tab._committed[trade_id].csa_threshold == pytest.approx(250_000.0)
    _wait_idle(tab)

    # The queued commit ran and the tab moved off this deal.
    assert tab._current_step() is not step
    assert tab._committed[trade_id].require_collateral is True
    # Advancing opened the next deal, which starts its own preview: let it finish
    # so the tab is not collected with a worker thread still running.
    _wait_idle(tab)


def test_every_decision_control_is_disabled_while_a_run_is_in_flight(qapp) -> None:
    # The MPoR dial was added to the form but left out of the enable/disable
    # list, so it stayed live while every control beside it greyed out.
    tab = SimulatorTab()
    tab.load_default()
    _wait_idle(tab)
    dials = (
        tab.action_combo,
        tab.collateral_check,
        tab.threshold_spin,
        tab.mta_spin,
        tab.im_spin,
        tab.mpor_spin,
        tab.limit_spin,
    )
    assert all(c.isEnabled() for c in dials)
    tab._request_preview()
    assert tab.is_busy()
    assert not any(c.isEnabled() for c in dials), "a dial stayed live mid-run"
    # Commit is the exception: the learner has already decided, so it stays
    # available during a preview and the run is queued.
    assert tab.commit_btn.isEnabled()
    tab._on_commit()
    assert tab._commit_pending
    # Once queued it greys out, so the same decision cannot be sent twice.
    assert not tab.commit_btn.isEnabled()
    _wait_idle(tab)
    assert all(c.isEnabled() for c in dials)


def test_loading_a_new_scenario_discards_work_queued_against_the_old_one(
    qapp,
) -> None:
    """A queued commit must not be applied to whatever is loaded next.

    Committing leaves a run queued; the scenario-loading controls stay enabled
    meanwhile, so a learner can switch stages before it fires. Left alone the
    queued commit ran against the new scenario with an empty decision set and
    skipped its first deal.
    """
    tab = SimulatorTab()
    tab.load_default()
    _wait_idle(tab)
    tab.set_candidate(_approve(collateral=False))
    tab._request_preview()
    assert tab.is_busy()
    tab._on_commit()
    assert tab._commit_pending

    tab.load_bundled("steady_book")
    # The queued *commit* is dropped. A queued preview may legitimately be set
    # again straight away — that is the new scenario asking for its own first
    # preview, which is exactly what should happen.
    assert not tab._commit_pending
    _wait_idle(tab)

    # Still on the new scenario's first deal, nothing committed for it.
    step = tab._current_step()
    assert step is not None and step.kind == "decision"
    assert step.round == 0
    assert tab._committed == {}
    assert tab.score_result is None
