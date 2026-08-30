"""The underwriting campaign: curriculum integrity, gating, and persistence.

Covers the three things the campaign must get right. Its stage list has to
resolve to real bundled scenarios in a coherent teaching order; a stage must
open only once the one before it is cleared (and stay open afterwards); and
progress has to survive a restart without a corrupt file taking the game down
with it.
"""

from __future__ import annotations

import json

import pytest

from duw.scenario import coaching
from duw.scenario.campaign import (
    CAMPAIGN,
    Campaign,
    CampaignProgress,
    CampaignStage,
    StageRecord,
    medal,
)
from duw.scenario.engine import run_scenario
from duw.scenario.io import list_bundled_scenarios, load_bundled_scenario
from duw.scenario.model import Decision, DecisionAction
from duw.scenario.scoring import score_scenario
from duw.store.progress import ProgressStore

FIRST = CAMPAIGN.stages[0]
SECOND = CAMPAIGN.stages[1]


# --------------------------------------------------------------------------- #
# Curriculum integrity
# --------------------------------------------------------------------------- #


def test_every_stage_resolves_to_a_bundled_scenario() -> None:
    bundled = dict(list_bundled_scenarios())
    for stage in CAMPAIGN:
        assert stage.scenario_name in bundled, stage.scenario_name


def test_every_bundled_scenario_is_used_by_the_campaign() -> None:
    # A shipped scenario nobody can reach through the campaign is dead content.
    for name, _title in list_bundled_scenarios():
        assert CAMPAIGN.index_of(name) >= 0, name


def test_campaign_starts_with_the_tutorial() -> None:
    first = load_bundled_scenario(CAMPAIGN.stages[0].scenario_name)
    assert first.meta.tutorial is True


def test_capstone_is_unaided() -> None:
    # The campaign has to end with the learner deciding alone: a coached final
    # stage would let the capstone be passed by following instructions.
    last = load_bundled_scenario(CAMPAIGN.stages[-1].scenario_name)
    assert last.meta.tutorial is False


def test_guided_stages_carry_a_full_walk_through() -> None:
    """A stage flagged ``tutorial`` must actually be hand-held.

    The flag turns coaching on automatically, so a scenario carrying it and
    nothing else would open a coach panel with nothing in it. Guided stages are
    the ones introducing a new mechanism, and each one owes the learner an
    opening and closing narration plus, on every deal, the coach's reasoning and
    the author's recommended decision to compare against.
    """
    guided = [
        (stage.scenario_name, load_bundled_scenario(stage.scenario_name))
        for stage in CAMPAIGN
        if load_bundled_scenario(stage.scenario_name).meta.tutorial
    ]
    assert guided, "the campaign should contain at least one guided stage"
    for name, scenario in guided:
        assert scenario.meta.intro, name
        assert scenario.meta.outro, name
        assert scenario.deal_stream, name
        for deal in scenario.deal_stream:
            assert deal.coaching, f"{name}:{deal.trade_id} has no coaching"
            assert deal.recommended is not None, (
                f"{name}:{deal.trade_id} has no recommended decision"
            )


def test_guided_stages_ask_the_learner_to_predict() -> None:
    # Predict-then-reveal is the mechanism that stops a guided stage becoming a
    # read-along, so every deal on a guided stage carries a question.
    for stage in CAMPAIGN:
        scenario = load_bundled_scenario(stage.scenario_name)
        if not scenario.meta.tutorial:
            continue
        for deal in scenario.deal_stream:
            assert deal.prediction is not None, (
                f"{stage.scenario_name}:{deal.trade_id} has no prediction"
            )


def test_stage_names_are_unique_and_ordered() -> None:
    names = CAMPAIGN.names
    assert len(set(names)) == len(names)
    for i, stage in enumerate(CAMPAIGN):
        assert CAMPAIGN.index_of(stage.scenario_name) == i
        assert stage.title.startswith(f"{i + 1}.")


def test_every_stage_has_a_concept_and_a_reachable_pass_mark() -> None:
    for stage in CAMPAIGN:
        assert stage.concept.strip()
        assert 0.0 < stage.pass_ratio <= 1.0


def test_index_of_and_stage_handle_unknown_names() -> None:
    assert CAMPAIGN.index_of("not-a-scenario") == -1
    assert CAMPAIGN.stage("not-a-scenario") is None
    assert CAMPAIGN.stage(FIRST.scenario_name) == FIRST


# --------------------------------------------------------------------------- #
# Gating
# --------------------------------------------------------------------------- #


def test_only_the_first_stage_is_open_to_a_new_learner() -> None:
    fresh = CampaignProgress()
    assert fresh.is_unlocked(CAMPAIGN, FIRST.scenario_name)
    for stage in CAMPAIGN.stages[1:]:
        assert not fresh.is_unlocked(CAMPAIGN, stage.scenario_name)
    assert fresh.next_stage(CAMPAIGN) == FIRST
    assert fresh.cleared_count(CAMPAIGN) == 0


def test_clearing_a_stage_opens_the_next_one() -> None:
    progress = CampaignProgress().with_result(FIRST, FIRST.pass_ratio, 10_000.0)
    assert progress.is_cleared(FIRST.scenario_name)
    assert progress.is_unlocked(CAMPAIGN, SECOND.scenario_name)
    assert progress.next_stage(CAMPAIGN) == SECOND
    # But not the one after that.
    assert not progress.is_unlocked(CAMPAIGN, CAMPAIGN.stages[2].scenario_name)


def test_a_failing_run_records_the_attempt_without_unlocking() -> None:
    progress = CampaignProgress().with_result(FIRST, FIRST.pass_ratio - 0.1, 500.0)
    record = progress.record(FIRST.scenario_name)
    assert record is not None
    assert record.plays == 1
    assert record.cleared is False
    assert not progress.is_unlocked(CAMPAIGN, SECOND.scenario_name)


def test_replaying_keeps_the_best_and_never_re_locks() -> None:
    progress = CampaignProgress().with_result(FIRST, 0.9, 9_000.0)
    worse = progress.with_result(FIRST, 0.2, 200.0)
    record = worse.record(FIRST.scenario_name)
    assert record.plays == 2
    assert record.best_ratio == pytest.approx(0.9)
    assert record.best_score == pytest.approx(9_000.0)
    # A weak replay must not close a stage the learner already opened.
    assert record.cleared is True
    assert worse.is_unlocked(CAMPAIGN, SECOND.scenario_name)


def test_practice_mode_opens_everything_without_clearing_it() -> None:
    practice = CampaignProgress().with_practice_mode(True)
    for stage in CAMPAIGN:
        assert practice.is_unlocked(CAMPAIGN, stage.scenario_name)
    # Unlocked is not cleared: progress is untouched.
    assert practice.cleared_count(CAMPAIGN) == 0
    assert practice.next_stage(CAMPAIGN) == FIRST


def test_a_scenario_outside_the_campaign_is_always_playable() -> None:
    # An instructor's own file must not be gated behind campaign progress.
    assert CampaignProgress().is_unlocked(CAMPAIGN, "some-instructor-file")


def test_completing_every_stage_reports_completion() -> None:
    progress = CampaignProgress()
    for stage in CAMPAIGN:
        progress = progress.with_result(stage, 1.0, 1_000.0)
    assert progress.is_complete(CAMPAIGN)
    assert progress.next_stage(CAMPAIGN) is None
    assert progress.cleared_count(CAMPAIGN) == len(CAMPAIGN)


def test_reset_clears_records_but_keeps_practice_preference() -> None:
    progress = (
        CampaignProgress()
        .with_practice_mode(True)
        .with_result(FIRST, 1.0, 1_000.0)
        .reset()
    )
    assert progress.records == ()
    assert progress.practice_mode is True


# --------------------------------------------------------------------------- #
# Medals
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [(1.2, "Gold"), (0.95, "Gold"), (0.8, "Silver"), (0.5, "Bronze"), (0.2, "")],
)
def test_medal_bands(ratio: float, expected: str) -> None:
    assert medal(ratio) == expected


def test_an_unplayed_stage_has_no_medal() -> None:
    assert StageRecord(scenario_name=FIRST.scenario_name).medal == ""


def test_medal_counts_tally_the_campaign() -> None:
    progress = (
        CampaignProgress().with_result(FIRST, 1.0, 1.0).with_result(SECOND, 0.8, 1.0)
    )
    counts = progress.medal_counts(CAMPAIGN)
    assert counts["Gold"] == 1
    assert counts["Silver"] == 1
    assert counts["Bronze"] == 0


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #


def test_progress_round_trips_through_the_store(tmp_path) -> None:
    store = ProgressStore(tmp_path / "campaign.json")
    progress = CampaignProgress().with_result(FIRST, 0.83, 12_345.0)
    store.save(progress)

    reloaded = ProgressStore(tmp_path / "campaign.json").load()
    assert reloaded == progress
    assert reloaded.is_unlocked(CAMPAIGN, SECOND.scenario_name)


def test_missing_store_loads_empty_progress(tmp_path) -> None:
    assert ProgressStore(tmp_path / "nothing.json").load() == CampaignProgress()


@pytest.mark.parametrize("content", ["", "   ", "not json at all", "[1, 2, 3]"])
def test_a_damaged_store_degrades_to_empty_rather_than_raising(
    tmp_path, content: str
) -> None:
    # Losing a saved place is a nuisance; refusing to start the game is worse.
    path = tmp_path / "campaign.json"
    path.write_text(content, encoding="utf-8")
    assert ProgressStore(path).load() == CampaignProgress()


def test_one_corrupt_record_does_not_discard_the_others(tmp_path) -> None:
    path = tmp_path / "campaign.json"
    path.write_text(
        json.dumps(
            {
                "practice_mode": False,
                "stages": [
                    {"scenario_name": FIRST.scenario_name, "plays": 1, "cleared": True},
                    {"plays": "nonsense"},  # missing name, unusable
                ],
            }
        ),
        encoding="utf-8",
    )
    loaded = ProgressStore(path).load()
    assert loaded.is_cleared(FIRST.scenario_name)
    assert len(loaded.records) == 1


def test_clear_removes_the_file(tmp_path) -> None:
    store = ProgressStore(tmp_path / "campaign.json")
    store.save(CampaignProgress().with_result(FIRST, 1.0, 1.0))
    store.clear()
    assert not store.path.exists()
    store.clear()  # idempotent


# --------------------------------------------------------------------------- #
# The campaign is actually winnable, and not by a blanket policy
# --------------------------------------------------------------------------- #


def test_campaign_object_supports_len_and_iteration() -> None:
    assert len(CAMPAIGN) == len(list(CAMPAIGN)) == len(CAMPAIGN.stages)
    tiny = Campaign(stages=(CampaignStage("x", "1. X", "concept"),))
    assert len(tiny) == 1


@pytest.mark.parametrize("stage", CAMPAIGN.stages, ids=lambda s: s.scenario_name)
def test_best_play_clears_every_stage(stage: CampaignStage) -> None:
    # The authored best play must actually pass the stage's own bar; otherwise
    # the campaign is unwinnable however well the learner plays.
    scenario = load_bundled_scenario(stage.scenario_name)
    assert coaching.has_benchmark(scenario)
    bench = coaching.benchmark_result(scenario)
    assert score_scenario(bench).risk_adjusted_score > 0.0
    # Best play scores itself, so its ratio is 1.0 by construction.
    assert 1.0 >= stage.pass_ratio


def _blanket(scenario, action: DecisionAction, collateral: bool) -> dict:
    return {
        deal.trade_id: Decision(
            trade_id=deal.trade_id,
            action=action,
            require_collateral=collateral,
            csa_threshold=0.0,
            limit=5_000_000.0,
        )
        for deal in scenario.deal_stream
    }


#: Benchmark scores are the same for every strategy test on a stage and each one
#: is a full engine run, so they are computed once per scenario.
_BENCH_CACHE: dict[str, float] = {}


def _benchmark_score(name: str, scenario) -> float:
    if name not in _BENCH_CACHE:
        _BENCH_CACHE[name] = score_scenario(
            coaching.benchmark_result(scenario)
        ).risk_adjusted_score
    return _BENCH_CACHE[name]


def _ratio(name: str, scenario, decisions: dict) -> float:
    bench = _benchmark_score(name, scenario)
    played = score_scenario(run_scenario(scenario, decisions)).risk_adjusted_score
    return played / bench if bench > 0 else 0.0


#: Stages carrying a scripted default, where discriminating between names is the
#: whole point and a blanket policy must therefore fail. The tutorial is excluded
#: deliberately: it is the coached on-ramp and is meant to be forgiving, so a
#: learner who over-collateralizes their way through it still advances to stage 2
#: rather than being stopped at the door.
_DEFAULTING_STAGES = [
    s
    for s in CAMPAIGN.stages
    if load_bundled_scenario(s.scenario_name).defaults
    and not load_bundled_scenario(s.scenario_name).meta.tutorial
]


@pytest.mark.parametrize("stage", _DEFAULTING_STAGES, ids=lambda s: s.scenario_name)
def test_blanket_collateral_does_not_clear_a_stage_with_a_default(
    stage: CampaignStage,
) -> None:
    # The load-bearing teaching property. If "demand collateral from everyone"
    # cleared these stages, the game would reward the one reflex that loses a
    # real desk its clients, and the learner would never have to read a
    # counterparty at all. Collateral has to cost enough that discriminating
    # between names is the only way through.
    scenario = load_bundled_scenario(stage.scenario_name)
    ratio = _ratio(
        stage.scenario_name,
        scenario,
        _blanket(scenario, DecisionAction.CONDITION, True),
    )
    assert ratio < stage.pass_ratio, (
        f"{stage.scenario_name}: blanket collateralization scored {ratio:.2f} "
        f"against a pass mark of {stage.pass_ratio:.2f}"
    )


@pytest.mark.parametrize("stage", _DEFAULTING_STAGES, ids=lambda s: s.scenario_name)
def test_blanket_approval_is_punished_where_a_name_defaults(
    stage: CampaignStage,
) -> None:
    # The opposite reflex: taking everything unsecured must land the default
    # loss and score far below both the best play and simply declining.
    scenario = load_bundled_scenario(stage.scenario_name)
    result = run_scenario(scenario, _blanket(scenario, DecisionAction.APPROVE, False))
    assert result.total_realized_loss > 0.0
    assert score_scenario(result).risk_adjusted_score < 0.0


def test_declining_everything_never_clears_a_stage() -> None:
    # Turning away all business is safe and worthless; it must not progress the
    # campaign anywhere.
    for stage in CAMPAIGN:
        scenario = load_bundled_scenario(stage.scenario_name)
        decisions = {
            d.trade_id: Decision(trade_id=d.trade_id, action=DecisionAction.DECLINE)
            for d in scenario.deal_stream
        }
        assert _ratio(stage.scenario_name, scenario, decisions) < stage.pass_ratio
