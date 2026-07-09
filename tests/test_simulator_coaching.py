"""Guided (tutorial) mode in the simulator tab. Headless via offscreen Qt.

Drives the coached flow: loading the tutorial turns guided mode on and computes
a best-play benchmark off-thread; the coach panel explains each deal and can
apply the recommended decision; following the best play to the end yields a
"Top marks" verdict.
"""

from __future__ import annotations

from PySide6.QtCore import QEventLoop, QTimer

from duw.scenario import coaching
from duw.scenario.model import DecisionAction
from duw.ui.tabs.simulator_tab import SimulatorTab


def _wait(tab: SimulatorTab, pred, max_ms: int = 60_000) -> None:
    """Run a nested event loop until ``pred()`` is true (or timeout)."""
    if pred():
        return
    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(20)
    poll.timeout.connect(lambda: loop.quit() if pred() else None)
    QTimer.singleShot(max_ms, loop.quit)
    poll.start()
    loop.exec()
    poll.stop()


def _wait_idle(tab: SimulatorTab) -> None:
    _wait(tab, lambda: not tab.is_busy())


def _settle(tab: SimulatorTab) -> None:
    """Wait for both the preview/commit run and the benchmark run to finish."""
    _wait(tab, lambda: not tab.is_busy() and tab.is_benchmark_ready())


def test_load_tutorial_enables_coached_mode(qapp) -> None:
    tab = SimulatorTab()
    tab.load_tutorial()
    _settle(tab)
    assert tab._coached is True
    assert tab.tutorial_check.isChecked()
    assert tab._scenario.meta.tutorial is True
    assert tab.is_benchmark_ready()
    # The coach panel is populated for the first deal.
    step = tab._current_step()
    assert step.kind == "decision"
    assert tab.coach_text.text()  # deal coaching text present
    assert "Recommended" in tab.coach_reco.text()


def test_apply_recommended_fills_the_controls(qapp) -> None:
    tab = SimulatorTab()
    tab.load_tutorial()
    _settle(tab)
    step = tab._current_step()
    recommended = step.deal.recommended
    assert recommended is not None
    tab._apply_recommended()
    _wait_idle(tab)
    assert tab._current_action() == recommended.action
    assert tab.collateral_check.isChecked() == recommended.require_collateral
    assert tab.limit_spin.value() == recommended.limit


def test_following_best_play_earns_top_marks(qapp) -> None:
    tab = SimulatorTab()
    tab.load_tutorial()
    _settle(tab)
    guard = 0
    while tab.score_result is None and guard < 50:
        guard += 1
        step = tab._current_step()
        assert step is not None
        if step.kind == "decision":
            tab._apply_recommended()
            _wait_idle(tab)
            tab._on_commit()
            _wait_idle(tab)
        elif step.kind == "default":
            assert tab.default_coach.text()  # tie-back coaching shown
            tab._on_continue()
            _wait_idle(tab)
        else:
            break
    _settle(tab)
    assert tab.stack.currentWidget() is tab._summary_page
    assert "Top marks" in tab.verdict_headline.text()
    assert tab.verdict_notes.text()
    assert tab.outro_label.text() == tab._scenario.meta.outro


def test_toggling_guided_mode_off_disables_coaching(qapp) -> None:
    tab = SimulatorTab()
    tab.load_tutorial()
    _settle(tab)
    tab.tutorial_check.setChecked(False)
    assert tab._coached is False
    # Re-rendering the current step should not populate the (hidden) coach panel.
    # The recommended-apply button is disabled outside guided mode.
    tab._update_enabled()
    assert not tab.apply_reco_btn.isEnabled()


def test_naive_play_is_scored_against_the_benchmark(qapp) -> None:
    # Approve everything open (no collateral) — the defaulter lands a loss, so
    # the verdict should not be "Top marks".
    tab = SimulatorTab()
    tab.load_tutorial()
    _settle(tab)
    guard = 0
    while tab.score_result is None and guard < 50:
        guard += 1
        step = tab._current_step()
        if step is None:
            break
        if step.kind == "decision":
            tab.set_candidate(
                coaching.recommended_decisions(tab._scenario)[step.deal.trade_id]
            )
            # Override to a plain open approval regardless of recommendation.
            tab.action_combo.setCurrentIndex(0)  # Approve
            tab.collateral_check.setChecked(False)
            _wait_idle(tab)
            tab._on_commit()
            _wait_idle(tab)
        elif step.kind == "default":
            tab._on_continue()
            _wait_idle(tab)
        else:
            break
    _settle(tab)
    assert tab.stack.currentWidget() is tab._summary_page
    assert "Top marks" not in tab.verdict_headline.text()


def test_first_deal_recommendation_is_to_collateralize(qapp) -> None:
    # The tutorial's first deal is the shaky name that defaults; best play is to
    # condition it on collateral.
    tab = SimulatorTab()
    tab.load_tutorial()
    _settle(tab)
    step = tab._current_step()
    assert step.deal.recommended.action == DecisionAction.CONDITION
    assert step.deal.recommended.require_collateral is True


def test_steady_book_via_picker_reaches_summary_with_no_default(qapp) -> None:
    tab = SimulatorTab()
    idx = tab.scenario_combo.findData("steady_book")
    assert idx >= 0
    tab.scenario_combo.setCurrentIndex(idx)
    tab._on_load_selected()
    _wait_idle(tab)
    seen_default = False
    guard = 0
    while tab.score_result is None and guard < 50:
        guard += 1
        step = tab._current_step()
        if step is None:
            break
        if step.kind == "decision":
            tab.action_combo.setCurrentIndex(0)  # Approve, open
            tab.collateral_check.setChecked(False)
            _wait_idle(tab)
            tab._on_commit()
            _wait_idle(tab)
        elif step.kind == "default":
            seen_default = True
            tab._on_continue()
            _wait_idle(tab)
        else:
            break
    assert not seen_default
    assert tab.stack.currentWidget() is tab._summary_page
    assert tab.score_result.breakdown.realized_losses == 0.0


def test_restart_scenario_resets_after_finishing(qapp) -> None:
    tab = SimulatorTab()
    tab.load_default()
    _wait_idle(tab)
    # Finish quickly by declining every deal (no open book, no default panels).
    guard = 0
    while tab.score_result is None and guard < 50:
        guard += 1
        step = tab._current_step()
        if step is None:
            break
        if step.kind == "decision":
            tab.action_combo.setCurrentIndex(2)  # Decline
            _wait_idle(tab)
            tab._on_commit()
            _wait_idle(tab)
        elif step.kind == "default":
            tab._on_continue()
            _wait_idle(tab)
        else:
            break
    assert tab.stack.currentWidget() is tab._summary_page
    # Reset and confirm we are back at the first decision with a clean slate.
    tab.restart_scenario()
    _wait_idle(tab)
    assert tab.score_result is None
    assert tab._current_step().kind == "decision"
    assert tab.stack.currentWidget() is tab._decision_page


def test_load_random_loads_a_playable_scenario(qapp) -> None:
    import random as _random

    tab = SimulatorTab()
    tab._rng = _random.Random(0)
    tab.load_random()
    _wait_idle(tab)
    assert tab._scenario is not None
    assert tab._scenario.meta.tutorial is False


def test_default_panel_reframes_a_protected_default(qapp) -> None:
    # Collateralizing the defaulter yields zero loss; the default panel should
    # reframe that as a successful underwrite rather than a failure.
    tab = SimulatorTab()
    tab.load_default()
    _wait_idle(tab)
    framing = ""
    guard = 0
    while tab.score_result is None and guard < 50:
        guard += 1
        step = tab._current_step()
        if step is None:
            break
        if step.kind == "decision":
            if "ACME" in step.deal.trade_id:
                tab.action_combo.setCurrentIndex(1)  # Condition
                tab.collateral_check.setChecked(True)
                tab.threshold_spin.setValue(0.0)
            else:
                tab.action_combo.setCurrentIndex(0)
                tab.collateral_check.setChecked(False)
            _wait_idle(tab)
            tab._on_commit()
            _wait_idle(tab)
        elif step.kind == "default":
            framing = tab.default_framing.text()
            tab._on_continue()
            _wait_idle(tab)
        else:
            break
    assert "successful underwrite" in framing
