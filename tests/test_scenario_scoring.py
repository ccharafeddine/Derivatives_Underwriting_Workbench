"""Scenario scoring tests.

Assert that the risk-adjusted scoring captures the underwriting trade-off:
approving profitable deals raises the score; a default on an under-collateralized
book inflicts a loss penalty that outweighs the revenue; over-collateralizing or
declining everything leaves revenue on the table and is not the top score; and
the component breakdown reconstructs the reported P&L exactly.
"""

from __future__ import annotations

import pytest

from duw.scenario.engine import run_scenario
from duw.scenario.io import load_bundled_scenario
from duw.scenario.model import Decision, DecisionAction
from duw.scenario.scoring import Scorer, ScoringParams, score_scenario

SAMPLE = "rising_rates_default"
ACME = "D1-ACME-IRS"  # counterparty defaults in the final round
GLOBEX = "D2-GBX-IRS"  # healthy name, survives


def _scenario():
    return load_bundled_scenario(SAMPLE)


def _approve(trade_id: str, collateral: bool = False, **kwargs) -> Decision:
    action = DecisionAction.CONDITION if collateral else DecisionAction.APPROVE
    return Decision(
        trade_id=trade_id,
        action=action,
        require_collateral=collateral,
        csa_threshold=0.0,
        **kwargs,
    )


def _decline(trade_id: str) -> Decision:
    return Decision(trade_id=trade_id, action=DecisionAction.DECLINE)


def _score(decisions: dict[str, Decision], params: ScoringParams | None = None):
    return score_scenario(run_scenario(_scenario(), decisions), params)


# Named strategies over the two-deal sample (Acme defaults, Globex survives).
def _reckless_all() -> dict[str, Decision]:
    return {ACME: _approve(ACME), GLOBEX: _approve(GLOBEX)}


def _cautious_all() -> dict[str, Decision]:
    return {
        ACME: _approve(ACME, collateral=True),
        GLOBEX: _approve(GLOBEX, collateral=True),
    }


def _decline_all() -> dict[str, Decision]:
    return {ACME: _decline(ACME), GLOBEX: _decline(GLOBEX)}


def _balanced() -> dict[str, Decision]:
    # Collateralize the name that will default; leave the healthy name open.
    return {ACME: _approve(ACME, collateral=True), GLOBEX: _approve(GLOBEX)}


# --------------------------------------------------------------------------- #
# Breakdown integrity
# --------------------------------------------------------------------------- #


def test_component_breakdown_sums_to_raw_pnl() -> None:
    score = _score(_balanced())
    b = score.breakdown
    reconstructed = (
        b.revenue
        + b.cva_collected
        - b.realized_losses
        - b.exposure_cost
        - b.breach_penalty
    )
    assert reconstructed == pytest.approx(score.raw_pnl)


def test_round_nets_sum_to_raw_pnl() -> None:
    score = _score(_balanced())
    assert sum(rs.net for rs in score.by_round) == pytest.approx(score.raw_pnl)


def test_risk_adjusted_never_exceeds_raw_pnl() -> None:
    # The risk penalty is non-negative, so it can only reduce the score.
    for decisions in (_reckless_all(), _cautious_all(), _balanced(), _decline_all()):
        score = _score(decisions)
        assert score.risk_adjusted_score <= score.raw_pnl + 1e-6
        assert score.breakdown.risk_penalty >= 0.0
        assert score.risk_adjusted_score == pytest.approx(
            score.raw_pnl - score.breakdown.risk_penalty
        )


def test_declining_everything_scores_zero() -> None:
    score = _score(_decline_all())
    assert score.raw_pnl == pytest.approx(0.0)
    assert score.risk_adjusted_score == pytest.approx(0.0)
    assert score.breakdown.revenue == pytest.approx(0.0)
    assert score.breakdown.realized_losses == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# The trade-off
# --------------------------------------------------------------------------- #


def test_approving_a_profitable_deal_raises_the_score() -> None:
    # Holding Acme declined, approving the healthy Globex deal (safely
    # collateralized) earns revenue and beats declining it.
    approve_globex = _score(
        {ACME: _decline(ACME), GLOBEX: _approve(GLOBEX, collateral=True)}
    )
    decline_globex = _score(_decline_all())
    assert approve_globex.raw_pnl > decline_globex.raw_pnl
    assert approve_globex.risk_adjusted_score > decline_globex.risk_adjusted_score
    assert approve_globex.breakdown.revenue > 0.0


def test_uncollateralized_default_loss_outweighs_its_revenue() -> None:
    # Approving Acme uncollateralized earns a fee + CVA but eats the full
    # realized loss when it defaults — a net far worse than simply declining it.
    reckless_acme = _score({ACME: _approve(ACME), GLOBEX: _decline(GLOBEX)})
    decline_acme = _score(_decline_all())

    assert reckless_acme.breakdown.realized_losses > 0.0
    # The loss dwarfs the revenue collected on the deal.
    assert reckless_acme.breakdown.realized_losses > 10 * (
        reckless_acme.breakdown.revenue + reckless_acme.breakdown.cva_collected
    )
    # So taking the reckless deal is much worse than not taking it at all.
    assert reckless_acme.raw_pnl < decline_acme.raw_pnl
    assert reckless_acme.risk_adjusted_score < decline_acme.risk_adjusted_score


def test_reckless_book_is_the_worst_outcome() -> None:
    scores = {
        "reckless": _score(_reckless_all()).risk_adjusted_score,
        "cautious": _score(_cautious_all()).risk_adjusted_score,
        "balanced": _score(_balanced()).risk_adjusted_score,
        "decline": _score(_decline_all()).risk_adjusted_score,
    }
    assert scores["reckless"] == min(scores.values())
    assert scores["reckless"] < 0.0


def test_over_caution_leaves_revenue_on_the_table() -> None:
    # Collateralizing every deal is safe but concedes spread on the survivor;
    # the balanced book (open on the healthy name) beats it, and both beat
    # declining everything. Neither extreme is optimal.
    cautious = _score(_cautious_all())
    balanced = _score(_balanced())
    decline = _score(_decline_all())

    assert balanced.risk_adjusted_score > cautious.risk_adjusted_score
    assert balanced.raw_pnl > cautious.raw_pnl
    assert cautious.risk_adjusted_score > decline.risk_adjusted_score


def test_balanced_book_is_the_top_score() -> None:
    # The intended lesson: protect the name that defaults, earn full spread on
    # the one that does not. That book should top every extreme.
    balanced = _score(_balanced()).risk_adjusted_score
    others = [
        _score(_reckless_all()).risk_adjusted_score,
        _score(_cautious_all()).risk_adjusted_score,
        _score(_decline_all()).risk_adjusted_score,
    ]
    assert balanced > max(others)


# --------------------------------------------------------------------------- #
# Breach and recovery levers
# --------------------------------------------------------------------------- #


def test_limit_breach_adds_penalty_and_risk_charge() -> None:
    params = ScoringParams()
    # A tiny limit forces the accepted Acme deal to breach.
    breaching = {
        ACME: _approve(ACME, limit=1_000.0),
        GLOBEX: _decline(GLOBEX),
    }
    not_breaching = {
        ACME: _approve(ACME, limit=500_000_000.0),
        GLOBEX: _decline(GLOBEX),
    }

    breach = _score(breaching, params)
    clean = _score(not_breaching, params)

    assert breach.breakdown.breach_penalty == pytest.approx(params.breach_penalty)
    assert clean.breakdown.breach_penalty == pytest.approx(0.0)
    # The breach costs both a flat P&L penalty and an extra risk charge.
    assert breach.raw_pnl == pytest.approx(clean.raw_pnl - params.breach_penalty)
    assert breach.breakdown.risk_penalty >= clean.breakdown.risk_penalty + (
        params.breach_risk_penalty
    )


def test_recovery_override_scales_the_loss() -> None:
    decisions = {ACME: _approve(ACME), GLOBEX: _decline(GLOBEX)}
    full_recovery = _score(decisions, ScoringParams(recovery_rate=1.0))
    no_recovery = _score(decisions, ScoringParams(recovery_rate=0.0))

    # Full recovery wipes the loss; zero recovery makes it the whole exposure.
    assert full_recovery.breakdown.realized_losses == pytest.approx(0.0)
    assert (
        no_recovery.breakdown.realized_losses > full_recovery.breakdown.realized_losses
    )


def test_scorer_and_wrapper_agree() -> None:
    run = run_scenario(_scenario(), _balanced())
    assert Scorer().score(run).raw_pnl == pytest.approx(score_scenario(run).raw_pnl)
