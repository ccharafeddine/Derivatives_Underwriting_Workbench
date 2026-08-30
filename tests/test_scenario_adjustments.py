"""Tests for the exposure, funding and sensitivity detail on a decision outcome.

The simulator's later campaign stages teach collateral mechanics, FVA/DVA and
the sensitivity report, and each of those needs the engine to surface numbers it
previously discarded. These tests pin that surfacing down: the collateral and
funding fields must come from the same pipeline run at no extra cost, and the
sensitivities must stay absent unless the scenario opts in — because opting in
multiplies the cost of every deal by the number of bumped risk factors.
"""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from duw.scenario.coaching import recommended_decisions
from duw.scenario.engine import run_scenario
from duw.scenario.io import load_bundled_scenario, scenario_from_dict, scenario_to_dict
from duw.scenario.model import Decision, DecisionAction

COLLATERAL = "collateral_terms"
FUNDING = "funding_and_own_credit"
SENSITIVITIES = "sensitivities_desk"


def _play(name: str):
    scenario = load_bundled_scenario(name)
    return scenario, run_scenario(scenario, recommended_decisions(scenario))


# --------------------------------------------------------------------------- #
# Collateral mechanics
# --------------------------------------------------------------------------- #


def test_outcome_reports_exposure_before_and_after_collateral() -> None:
    _scenario, result = _play(COLLATERAL)
    for outcome in result.decisions:
        # The uncollateralized peak is what the trade created; the collateralized
        # peak is what survived the CSA. Reporting only the second would hide the
        # benefit the terms actually bought.
        assert outcome.uncollateralized_peak_pfe == pytest.approx(outcome.peak_pfe)
        assert outcome.collateralized_peak_pfe <= outcome.uncollateralized_peak_pfe
        assert outcome.mpor_days == 10


def test_a_zero_threshold_csa_still_leaves_gap_risk() -> None:
    # The point of the collateral stage: a zero threshold does not mean zero
    # exposure, because nothing is collected during the margin period of risk.
    _scenario, result = _play(COLLATERAL)
    first = result.decisions[0]
    assert first.collateralized_peak_pfe > 0.0
    assert first.collateralized_peak_pfe < 0.25 * first.peak_pfe


def test_a_longer_margin_period_leaves_more_exposure_uncovered() -> None:
    scenario = load_bundled_scenario(COLLATERAL)
    trade_ids = [deal.trade_id for deal in scenario.deal_stream]

    def run_with(mpor_days: int):
        decisions = {
            tid: Decision(
                trade_id=tid,
                action=DecisionAction.CONDITION,
                require_collateral=True,
                csa_threshold=0.0,
                csa_mpor_days=mpor_days,
                limit=6_000_000.0,
            )
            for tid in trade_ids
        }
        return run_scenario(scenario, decisions).decisions[-1]

    quick, slow = run_with(5), run_with(30)
    assert slow.mpor_days == 30
    assert slow.collateralized_peak_pfe > quick.collateralized_peak_pfe


def test_a_threshold_is_exposure_the_csa_never_secures() -> None:
    scenario = load_bundled_scenario(COLLATERAL)
    trade_ids = [deal.trade_id for deal in scenario.deal_stream]

    def loss_with(threshold: float) -> float:
        decisions = {
            tid: Decision(
                trade_id=tid,
                action=DecisionAction.CONDITION,
                require_collateral=True,
                csa_threshold=threshold,
                limit=6_000_000.0,
            )
            for tid in trade_ids
        }
        result = run_scenario(scenario, decisions)
        return result.total_realized_loss

    # At a zero threshold the close-out is fully covered. Granting a threshold
    # hands that slice back as an unsecured claim, lost at (1 - recovery).
    assert loss_with(0.0) == pytest.approx(0.0)
    recovery = scenario.counterparties[0].recovery_rate
    assert loss_with(3_000_000.0) == pytest.approx(
        (1.0 - recovery) * 3_000_000.0, rel=1e-6
    )


# --------------------------------------------------------------------------- #
# Funding and own credit
# --------------------------------------------------------------------------- #


def test_funding_scenario_reports_fva_and_a_one_sided_option_has_no_dva() -> None:
    _scenario, result = _play(FUNDING)
    swaption = result.decisions[0]
    # A bought option can only ever be an asset, so the counterparty is never
    # exposed to us: there is nothing for own-credit risk to attach to.
    assert swaption.dva == pytest.approx(0.0)
    assert swaption.bcva == pytest.approx(swaption.cva)
    # With nothing to net against, the whole profile is funded: FVA is a cost.
    assert swaption.fva > 0.0


def test_a_profile_leaning_against_us_funds_itself() -> None:
    _scenario, result = _play(FUNDING)
    swap = result.decisions[1]
    # The par payer swap leans out of the money on this downward-sloping curve,
    # so expected negative exposure exceeds expected exposure and both the
    # funding leg and BCVA change sign.
    assert swap.fva < 0.0
    assert swap.dva > swap.cva
    assert swap.bcva < 0.0


def test_fva_is_zero_when_the_scenario_funds_at_no_spread() -> None:
    scenario = load_bundled_scenario(COLLATERAL)
    assert scenario.settings.funding_spread == 0.0
    result = run_scenario(scenario, recommended_decisions(scenario))
    assert all(o.fva == pytest.approx(0.0) for o in result.decisions)


# --------------------------------------------------------------------------- #
# Sensitivities (opt-in)
# --------------------------------------------------------------------------- #


def test_sensitivities_are_absent_unless_the_scenario_opts_in() -> None:
    scenario = load_bundled_scenario(COLLATERAL)
    assert scenario.settings.compute_sensitivities is False
    result = run_scenario(scenario, recommended_decisions(scenario))
    for outcome in result.decisions:
        assert outcome.dv01_pfe is None
        assert outcome.dv01_cva is None
        assert outcome.cs01_cva is None
        assert outcome.fx_delta_pfe is None
        assert outcome.fx_delta_cva is None


def test_opting_in_populates_every_sensitivity() -> None:
    scenario, result = _play(SENSITIVITIES)
    assert scenario.settings.compute_sensitivities is True
    for outcome in result.decisions:
        for value in (
            outcome.dv01_pfe,
            outcome.dv01_cva,
            outcome.cs01_cva,
            outcome.fx_delta_pfe,
            outcome.fx_delta_cva,
        ):
            assert value is not None
            assert not math.isnan(value)


def test_a_single_currency_swap_has_exactly_zero_fx_delta() -> None:
    # Not merely small: there is no foreign leg for the FX bump to reach, and
    # the sensitivities stage teaches the learner to expect a hard zero here.
    _scenario, result = _play(SENSITIVITIES)
    swap = result.decisions[0]
    assert swap.fx_delta_pfe == pytest.approx(0.0)
    assert swap.fx_delta_cva == pytest.approx(0.0)
    # Its rate sensitivity, by contrast, is large and positive: a payer swap's
    # exposure grows as rates rise.
    assert swap.dv01_pfe > 0.0


def test_an_fx_forward_runs_on_currency_rather_than_rates() -> None:
    _scenario, result = _play(SENSITIVITIES)
    swap, forward = result.decisions[0], result.decisions[1]
    assert abs(forward.fx_delta_pfe) > abs(forward.dv01_pfe)
    assert abs(forward.dv01_pfe) < abs(swap.dv01_pfe)


def test_the_sensitivities_flag_survives_a_save_load_round_trip() -> None:
    scenario = load_bundled_scenario(SENSITIVITIES)
    restored = scenario_from_dict(scenario_to_dict(scenario))
    assert restored.settings.compute_sensitivities is True
    off = replace(
        scenario, settings=replace(scenario.settings, compute_sensitivities=False)
    )
    assert (
        scenario_from_dict(scenario_to_dict(off)).settings.compute_sensitivities
        is False
    )
