"""Guided-mode coaching: benchmark, verdict, and the coaching data round-trip.

Headless (no Qt). Checks that the tutorial scenario carries its coaching fields
through IO, that the best-play benchmark scores higher than a naive play, that
the verdict bands and per-round notes attribute the gap correctly, and that the
new scoreboard glossary terms resolve.
"""

from __future__ import annotations

import pytest

from duw.glossary import lookup
from duw.scenario import coaching
from duw.scenario.engine import ScenarioEngine
from duw.scenario.io import (
    list_bundled_scenarios,
    list_playable_scenarios,
    load_bundled_scenario,
    scenario_from_dict,
    scenario_to_dict,
)
from duw.scenario.model import Decision, DecisionAction
from duw.scenario.scoring import score_scenario

TUTORIAL = "tutorial_intro"
SAMPLE = "rising_rates_default"
STEADY = "steady_book"


# ---------------------------------------------------------------------------
# Coaching data model + IO
# ---------------------------------------------------------------------------


def test_tutorial_scenario_carries_coaching_fields() -> None:
    s = load_bundled_scenario(TUTORIAL)
    assert s.meta.tutorial is True
    assert s.meta.intro and s.meta.outro
    # Every deal has coaching text and a recommended decision.
    for deal in s.deal_stream:
        assert deal.coaching
        assert deal.recommended is not None
        # The recommended decision's trade id is injected from the deal.
        assert deal.recommended.trade_id == deal.trade_id
    # The default carries a tie-back coaching note.
    assert all(e.coaching for e in s.defaults)


def test_coaching_fields_round_trip_through_json() -> None:
    s = load_bundled_scenario(TUTORIAL)
    s2 = scenario_from_dict(scenario_to_dict(s))
    assert s2.meta.tutorial == s.meta.tutorial
    assert s2.meta.intro == s.meta.intro
    assert s2.meta.outro == s.meta.outro
    assert s2.deal_stream[0].coaching == s.deal_stream[0].coaching
    assert s2.deal_stream[0].recommended == s.deal_stream[0].recommended
    assert s2.defaults[0].coaching == s.defaults[0].coaching


def test_plain_scenario_has_no_coaching_by_default() -> None:
    # Backward compatibility: a scenario authored without the guided-mode fields
    # loads with them empty/absent, and reports no benchmark until recommended
    # decisions are added.
    s = load_bundled_scenario(SAMPLE)
    assert s.meta.intro == "" and s.meta.outro == ""
    # The sample now scripts recommended decisions, so it does have a benchmark.
    assert coaching.has_benchmark(s)


# ---------------------------------------------------------------------------
# Benchmark and verdict
# ---------------------------------------------------------------------------


def _naive_all_open(scenario) -> dict[str, Decision]:
    return {
        d.trade_id: Decision(d.trade_id, DecisionAction.APPROVE, limit=3_000_000.0)
        for d in scenario.deal_stream
    }


def test_recommended_decisions_cover_every_deal() -> None:
    s = load_bundled_scenario(TUTORIAL)
    recs = coaching.recommended_decisions(s)
    assert set(recs) == {d.trade_id for d in s.deal_stream}


def test_best_play_beats_naive_and_takes_no_loss() -> None:
    s = load_bundled_scenario(TUTORIAL)
    bench = coaching.benchmark_result(s)
    bench_score = score_scenario(bench)
    # Best play carries no realized loss (the defaulter was collateralized).
    assert sum(d.realized_loss for d in bench.defaults) == 0.0
    assert bench_score.risk_adjusted_score > 0.0

    naive = ScenarioEngine(s).run(_naive_all_open(s))
    naive_score = score_scenario(naive)
    assert naive_score.risk_adjusted_score < bench_score.risk_adjusted_score


def test_verdict_top_marks_when_matching_best_play() -> None:
    s = load_bundled_scenario(TUTORIAL)
    bench = coaching.benchmark_result(s)
    verdict = coaching.evaluate(s, bench, bench)
    assert verdict.band == "Top marks"
    assert verdict.ratio == 1.0
    # Matching best play still earns the positive "avoided every default" note.
    assert any("avoided every scripted default" in n for n in verdict.notes)


def test_verdict_flags_a_taken_default_loss() -> None:
    s = load_bundled_scenario(TUTORIAL)
    bench = coaching.benchmark_result(s)
    naive = ScenarioEngine(s).run(_naive_all_open(s))
    verdict = coaching.evaluate(s, naive, bench)
    assert verdict.band == "Loss-making book"
    assert verdict.student_score < verdict.target_score
    # A note attributes the shortfall to a default loss that needed collateral.
    assert any("default loss" in n and "collateral" in n for n in verdict.notes)


def test_on_track_label_bands() -> None:
    assert coaching.on_track_label(110.0, 100.0) == "Ahead of the best play"
    assert coaching.on_track_label(95.0, 100.0) == "On track"
    assert coaching.on_track_label(60.0, 100.0) == "Slightly behind"
    assert coaching.on_track_label(10.0, 100.0) == "Behind"
    # A non-positive benchmark degrades gracefully.
    assert coaching.on_track_label(0.0, 0.0) == "On track"


def test_cumulative_net_sums_completed_rounds() -> None:
    s = load_bundled_scenario(TUTORIAL)
    score = score_scenario(coaching.benchmark_result(s))
    full = sum(rs.net for rs in score.by_round)
    assert coaching.cumulative_net(score, up_to_round=99) == full
    assert coaching.cumulative_net(score, up_to_round=-1) == 0.0


# ---------------------------------------------------------------------------
# Glossary
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# No-default scenario + bundled listing
# ---------------------------------------------------------------------------


def test_steady_book_has_no_defaults_and_a_benchmark() -> None:
    s = load_bundled_scenario(STEADY)
    assert s.defaults == ()
    assert coaching.has_benchmark(s)
    bench = coaching.benchmark_result(s)
    # Nobody defaults, so the best play carries no realized loss and scores well.
    assert sum(d.realized_loss for d in bench.defaults) == 0.0
    assert score_scenario(bench).risk_adjusted_score > 0.0


def test_steady_book_best_play_beats_over_caution() -> None:
    # With no default to protect against, leaving deals open beats
    # collateralizing everything (which concedes spread for nothing).
    s = load_bundled_scenario(STEADY)
    bench = coaching.benchmark_result(s)
    cautious = ScenarioEngine(s).run(
        {
            d.trade_id: Decision(
                d.trade_id,
                DecisionAction.CONDITION,
                require_collateral=True,
                csa_threshold=0.0,
                limit=4_000_000.0,
            )
            for d in s.deal_stream
        }
    )
    verdict = coaching.evaluate(s, cautious, bench)
    assert verdict.student_score < verdict.target_score
    assert verdict.band != "Loss-making book"  # over-caution loses value, not money
    assert any("less revenue" in n for n in verdict.notes)


def test_at_least_seven_playable_scenarios() -> None:
    play = list_playable_scenarios()
    assert len(play) >= 7
    names = dict(play)
    assert TUTORIAL not in names  # the walk-through is not in the random pool


@pytest.mark.parametrize("name", [n for n, _ in list_playable_scenarios()])
def test_bundled_playable_scenario_best_play_is_sound(name) -> None:
    # Every shipped playable scenario must have a best play that carries no
    # realized loss and scores positively — the property the generator enforced.
    s = load_bundled_scenario(name)
    assert coaching.has_benchmark(s)
    bench = coaching.benchmark_result(s)
    assert sum(d.realized_loss for d in bench.defaults) == 0.0
    assert score_scenario(bench).risk_adjusted_score > 0.0


def test_list_bundled_scenarios_includes_the_shipped_set() -> None:
    listed = dict(list_bundled_scenarios())
    for name in (SAMPLE, TUTORIAL, STEADY):
        assert name in listed
    # Titles are non-empty and the list is sorted by title.
    titles = [title for _name, title in list_bundled_scenarios()]
    assert all(titles)
    assert titles == sorted(titles)


def test_scoreboard_terms_have_glossary_entries() -> None:
    for term in (
        "Raw P&L",
        "Risk-adjusted score",
        "Revenue",
        "CVA collected",
        "Realized losses",
        "Exposure cost",
        "Breach penalty",
        "Risk penalty",
    ):
        assert lookup(term) is not None, term
    # Longest-match precedence: "CVA collected" is not shadowed by "CVA".
    assert lookup("CVA collected") != lookup("CVA")
