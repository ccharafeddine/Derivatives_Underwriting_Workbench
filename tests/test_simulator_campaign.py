"""The simulator's campaign shell, predict-then-reveal, and credit dossier.

Headless via offscreen Qt. Drives the tab the way a learner does: open the stage
list, find everything past stage one locked, play the first stage to the end,
and confirm the result is graded, recorded, and the next stage opened. Also
covers the two mechanics that make a round a judgment rather than a reflex —
withholding the analytics until the learner commits to a prediction, and showing
the counterparty's credit evidence so there is something to judge on.
"""

from __future__ import annotations

from PySide6.QtCore import QEventLoop, QTimer

from duw.scenario.campaign import CAMPAIGN
from duw.scenario.model import DecisionAction
from duw.store.progress import ProgressStore
from duw.ui.tabs.simulator_tab import PREDICTION_SKIPPED, SimulatorTab

TUTORIAL = CAMPAIGN.stages[0]
SECOND = CAMPAIGN.stages[1]


def _wait(pred, max_ms: int = 120_000) -> None:
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


def _idle(tab: SimulatorTab) -> None:
    _wait(lambda: not tab.is_busy())


def _settled(tab: SimulatorTab) -> None:
    _wait(lambda: not tab.is_busy() and tab.is_benchmark_ready())


def _tab(tmp_path) -> SimulatorTab:
    return SimulatorTab(progress_store=ProgressStore(tmp_path / "campaign.json"))


def _play_out(tab: SimulatorTab, *, follow_recommendation: bool) -> None:
    """Play the loaded scenario to its summary, one step at a time."""
    guard = 0
    while tab.score_result is None and guard < 60:
        guard += 1
        step = tab._current_step()
        if step is None:
            break
        if step.kind == "decision":
            if follow_recommendation:
                tab._apply_recommended()
            else:
                tab.action_combo.setCurrentIndex(0)  # Approve, open
                tab.collateral_check.setChecked(False)
            _idle(tab)
            tab._on_commit()
            _idle(tab)
        elif step.kind == "default":
            tab._on_continue()
            _idle(tab)
        else:
            break
    _settled(tab)


# --------------------------------------------------------------------------- #
# The stage list
# --------------------------------------------------------------------------- #


def test_tab_opens_on_the_campaign_with_only_stage_one_unlocked(qapp, tmp_path) -> None:
    tab = _tab(tmp_path)
    assert tab.stack.currentWidget() is tab._campaign_page
    assert tab.stage_list.count() == len(CAMPAIGN)
    first = tab.stage_list.item(0)
    assert first.flags() & tab.stage_list.item(0).flags()  # enabled
    assert "🔒" not in first.text()
    assert "🔒" in tab.stage_list.item(1).text()
    assert "0 of" in tab.campaign_summary.text()


def test_selecting_a_locked_stage_explains_how_to_open_it(qapp, tmp_path) -> None:
    tab = _tab(tmp_path)
    tab.stage_list.setCurrentRow(1)
    assert not tab.play_stage_btn.isEnabled()
    assert "Locked" in tab.stage_detail.text()
    assert CAMPAIGN.stages[0].title in tab.stage_detail.text()


def test_stage_detail_shows_the_concept_and_objectives(qapp, tmp_path) -> None:
    tab = _tab(tmp_path)
    tab.stage_list.setCurrentRow(0)
    detail = tab.stage_detail.text()
    assert TUTORIAL.concept[:30] in detail
    assert "come away able to" in detail


def test_practice_mode_unlocks_every_stage_and_persists(qapp, tmp_path) -> None:
    tab = _tab(tmp_path)
    tab.practice_check.setChecked(True)
    for row in range(tab.stage_list.count()):
        assert "🔒" not in tab.stage_list.item(row).text()
    # Reopening the tab against the same store keeps the preference.
    reopened = _tab(tmp_path)
    assert reopened.practice_check.isChecked()


def test_continue_campaign_loads_the_first_uncleared_stage(qapp, tmp_path) -> None:
    tab = _tab(tmp_path)
    tab.continue_campaign()
    _idle(tab)
    assert tab._stage_name == TUTORIAL.scenario_name
    assert tab.stack.currentWidget() is tab._decision_page


def test_reset_progress_relocks_the_campaign(qapp, tmp_path) -> None:
    store = ProgressStore(tmp_path / "campaign.json")
    tab = SimulatorTab(progress_store=store)
    tab._progress = tab._progress.with_result(TUTORIAL, 1.0, 1000.0)
    tab._save_progress()
    tab._render_campaign()
    assert "🔒" not in tab.stage_list.item(1).text()

    tab.reset_progress()
    assert "🔒" in tab.stage_list.item(1).text()
    assert store.load().cleared_count(CAMPAIGN) == 0


# --------------------------------------------------------------------------- #
# Playing a stage records progress
# --------------------------------------------------------------------------- #


def test_clearing_stage_one_records_it_and_opens_stage_two(qapp, tmp_path) -> None:
    store = ProgressStore(tmp_path / "campaign.json")
    tab = SimulatorTab(progress_store=store)
    tab.play_stage(TUTORIAL)
    _settled(tab)
    _play_out(tab, follow_recommendation=True)

    assert tab.stack.currentWidget() is tab._summary_page
    # Recorded in memory, on screen, and on disk.
    record = tab._progress.record(TUTORIAL.scenario_name)
    assert record is not None and record.cleared
    assert record.best_ratio >= TUTORIAL.pass_ratio
    assert "Stage cleared" in tab.stage_outcome.text()
    assert tab._progress.is_unlocked(CAMPAIGN, SECOND.scenario_name)
    assert store.load().is_cleared(TUTORIAL.scenario_name)


def test_a_weak_run_is_recorded_but_does_not_clear(qapp, tmp_path) -> None:
    store = ProgressStore(tmp_path / "campaign.json")
    tab = SimulatorTab(progress_store=store)
    tab.play_stage(TUTORIAL)
    _settled(tab)
    # Approve everything open: the defaulters land real losses.
    _play_out(tab, follow_recommendation=False)

    record = tab._progress.record(TUTORIAL.scenario_name)
    assert record is not None
    assert record.plays == 1
    assert record.cleared is False
    assert "not cleared" in tab.stage_outcome.text()
    assert not tab._progress.is_unlocked(CAMPAIGN, SECOND.scenario_name)


def test_the_run_is_recorded_only_once(qapp, tmp_path) -> None:
    tab = _tab(tmp_path)
    tab.play_stage(TUTORIAL)
    _settled(tab)
    _play_out(tab, follow_recommendation=True)
    plays = tab._progress.record(TUTORIAL.scenario_name).plays
    # A late benchmark or a repeated summary render must not double-count.
    tab._record_stage_result()
    tab._render_summary()
    assert tab._progress.record(TUTORIAL.scenario_name).plays == plays


def test_summary_grades_the_run_skill_by_skill(qapp, tmp_path) -> None:
    tab = _tab(tmp_path)
    tab.play_stage(TUTORIAL)
    _settled(tab)
    _play_out(tab, follow_recommendation=True)
    assert not tab.skills_group.isHidden()
    assert tab.skills_table.rowCount() == 4  # the four graded skills


# --------------------------------------------------------------------------- #
# Predict-then-reveal
# --------------------------------------------------------------------------- #


def test_analytics_are_withheld_until_the_prediction_is_answered(
    qapp, tmp_path
) -> None:
    tab = _tab(tmp_path)
    tab.play_stage(TUTORIAL)
    _settled(tab)
    step = tab._current_step()
    assert step.deal.prediction is not None
    # isHidden, not isVisible: the tab is never shown in a headless run, so
    # isVisible is False for everything regardless of what was set.
    assert not tab.prediction_group.isHidden()
    # Nothing revealed yet.
    assert "hidden until you answer" in tab.consequence_header.text()
    assert tab.recommendation_label.text() == ""

    tab.prediction_buttons.button(step.deal.prediction.correct_index).setChecked(True)
    tab._on_answer_prediction()
    assert "Correct" in tab.prediction_feedback.text()
    assert "Consequences before you commit" in tab.consequence_header.text()
    assert tab.recommendation_label.text() != ""


def test_a_wrong_prediction_still_reveals_and_shows_the_answer(qapp, tmp_path) -> None:
    tab = _tab(tmp_path)
    tab.play_stage(TUTORIAL)
    _settled(tab)
    prediction = tab._current_step().deal.prediction
    wrong = (prediction.correct_index + 1) % len(prediction.options)
    tab.prediction_buttons.button(wrong).setChecked(True)
    tab._on_answer_prediction()
    assert "Not quite" in tab.prediction_feedback.text()
    assert (
        prediction.options[prediction.correct_index] in tab.prediction_feedback.text()
    )
    assert "Consequences before you commit" in tab.consequence_header.text()


def test_answering_nothing_prompts_rather_than_revealing(qapp, tmp_path) -> None:
    tab = _tab(tmp_path)
    tab.play_stage(TUTORIAL)
    _settled(tab)
    tab._on_answer_prediction()  # no option chosen
    assert "Pick an option" in tab.prediction_feedback.text()
    assert "hidden until you answer" in tab.consequence_header.text()


def test_skipping_reveals_without_scoring_the_question(qapp, tmp_path) -> None:
    tab = _tab(tmp_path)
    tab.play_stage(TUTORIAL)
    _settled(tab)
    trade_id = tab._current_step().deal.trade_id
    tab._on_skip_prediction()
    assert tab._predictions[trade_id] == PREDICTION_SKIPPED
    assert "Consequences before you commit" in tab.consequence_header.text()
    assert tab.prediction_tally() == (0, 0)  # a skip is not a wrong answer


def test_prediction_tally_counts_only_answered_questions(qapp, tmp_path) -> None:
    tab = _tab(tmp_path)
    tab.play_stage(TUTORIAL)
    _settled(tab)
    step = tab._current_step()
    tab.prediction_buttons.button(step.deal.prediction.correct_index).setChecked(True)
    tab._on_answer_prediction()
    assert tab.prediction_tally() == (1, 1)
    tab._on_commit()
    _idle(tab)
    tab._on_skip_prediction()
    assert tab.prediction_tally() == (1, 1)


def test_committing_is_never_blocked_by_an_unanswered_prediction(
    qapp, tmp_path
) -> None:
    # The question teaches; it must not trap a learner who wants to get on.
    tab = _tab(tmp_path)
    tab.play_stage(TUTORIAL)
    _settled(tab)
    first = tab._current_step().deal.trade_id
    tab._on_commit()
    _idle(tab)
    assert first in tab._committed


# --------------------------------------------------------------------------- #
# The credit dossier
# --------------------------------------------------------------------------- #


def test_dossier_shows_the_credit_evidence_for_the_counterparty(qapp, tmp_path) -> None:
    tab = _tab(tmp_path)
    tab.play_stage(TUTORIAL)
    _settled(tab)
    labels = {
        tab.dossier_table.item(r, 0).text()
        for r in range(tab.dossier_table.rowCount())
        if tab.dossier_table.item(r, 0)
    }
    for expected in (
        "Model grade",
        "Distance to default",
        "1y PD (Merton)",
        "Altman Z",
        "Altman zone",
        "CDS 5y spread",
    ):
        assert expected in labels


def test_dossier_separates_a_weak_name_from_a_strong_one(qapp, tmp_path) -> None:
    # The evidence has to actually discriminate, or there is nothing to read.
    from duw.scenario.coaching import benchmark_result
    from duw.scenario.io import load_bundled_scenario

    scenario = load_bundled_scenario("credit_evidence")
    outcomes = {o.counterparty_id: o for o in benchmark_result(scenario).decisions}
    strong, weak = outcomes["STAL"], outcomes["IRON"]
    assert weak.merton_pd > strong.merton_pd
    assert weak.distance_to_default < strong.distance_to_default
    assert weak.cds_spread_5y > strong.cds_spread_5y


def test_a_committee_set_limit_is_shown_and_cannot_be_edited(qapp, tmp_path) -> None:
    tab = _tab(tmp_path)
    tab._progress = tab._progress.with_practice_mode(True)
    tab.load_bundled("netting_benefit")
    _settled(tab)
    assert tab.limit_spin.isReadOnly()
    assert tab.limit_spin.value() == 4_000_000.0
    assert "credit committee" in tab.limit_spin.toolTip()


def test_a_learner_set_limit_stays_editable(qapp, tmp_path) -> None:
    tab = _tab(tmp_path)
    tab.play_stage(TUTORIAL)
    _settled(tab)
    assert not tab.limit_spin.isReadOnly()


def test_netting_detail_appears_once_the_client_has_a_book(qapp, tmp_path) -> None:
    tab = _tab(tmp_path)
    tab._progress = tab._progress.with_practice_mode(True)
    tab.load_bundled("netting_benefit")
    _settled(tab)
    # First trade: nothing to net against, so no incremental row.
    labels = lambda: {  # noqa: E731 - terse local for a repeated read
        tab.consequence_table.item(r, 0).text()
        for r in range(tab.consequence_table.rowCount())
        if tab.consequence_table.item(r, 0)
    }
    tab._on_skip_prediction()
    assert "Incremental exposure" not in labels()

    tab.action_combo.setCurrentIndex(0)  # Approve
    tab.collateral_check.setChecked(False)
    _idle(tab)
    tab._on_commit()
    _idle(tab)
    tab._on_skip_prediction()
    assert "Incremental exposure" in labels()
    assert "Netting set before this trade" in labels()


def test_free_play_still_reaches_the_picker_and_back(qapp, tmp_path) -> None:
    tab = _tab(tmp_path)
    tab._show_prompt()
    assert tab.stack.currentWidget() is tab._prompt_page
    tab.show_campaign()
    assert tab.stack.currentWidget() is tab._campaign_page


def test_a_scenario_from_outside_the_campaign_records_nothing(qapp, tmp_path) -> None:
    from duw.scenario.io import save_scenario

    tab = _tab(tmp_path)
    path = tmp_path / "custom.json"
    save_scenario(
        __import__(
            "duw.scenario.io", fromlist=["load_bundled_scenario"]
        ).load_bundled_scenario("steady_book"),
        path,
    )
    tab.load_from_path(str(path))
    _idle(tab)
    assert tab._stage_name is None
    tab._record_stage_result()
    assert tab._progress.records == ()


def test_decision_action_enum_is_reachable_from_the_controls(qapp, tmp_path) -> None:
    tab = _tab(tmp_path)
    tab.play_stage(TUTORIAL)
    _settled(tab)
    tab.action_combo.setCurrentIndex(1)
    assert tab._current_action() == DecisionAction.CONDITION


def test_campaign_blurb_states_the_real_stage_count(qapp, tmp_path) -> None:
    """The header count must come from the campaign, not from prose.

    It read "Thirteen stages" for a while after the campaign grew to 17, which
    the stage list right underneath it flatly contradicted.
    """
    tab = SimulatorTab(progress_store=ProgressStore(tmp_path / "campaign.json"))
    tab.show_campaign()
    blurb = tab.framing.text()
    assert f"{len(CAMPAIGN)} stages" in blurb
    assert "Thirteen" not in blurb
