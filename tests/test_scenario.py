"""Scenario simulator backbone tests.

Covers the save/load round-trip of the bundled sample scenario, an end-to-end
run against a scripted list of decisions, the realized-loss contrast between an
under-collateralized and a well-collateralized approval when a counterparty
defaults, and the validation errors the loader raises on bad input.
"""

from __future__ import annotations

import json

import pytest

from duw.scenario.engine import run_scenario
from duw.scenario.io import (
    ScenarioError,
    ScenarioValidationError,
    load_bundled_scenario,
    load_scenario,
    save_scenario,
    scenario_from_dict,
    scenario_to_dict,
)
from duw.scenario.model import Decision, DecisionAction

SAMPLE = "rising_rates_default"
ACME_DEAL = "D1-ACME-IRS"
GLOBEX_DEAL = "D2-GBX-IRS"


def _sample():
    return load_bundled_scenario(SAMPLE)


def _approve(trade_id: str, **kwargs) -> Decision:
    return Decision(trade_id=trade_id, action=DecisionAction.APPROVE, **kwargs)


# --------------------------------------------------------------------------- #
# Save / load round-trip
# --------------------------------------------------------------------------- #


def test_bundled_sample_loads_and_validates() -> None:
    scenario = _sample()
    assert scenario.meta.n_rounds == 3
    assert {cp.counterparty_id for cp in scenario.counterparties} == {"CP001", "CP002"}
    assert scenario.defaults[0].counterparty_id == "CP001"


def test_scenario_round_trips_through_save_load(tmp_path) -> None:
    scenario = _sample()
    path = tmp_path / "scenario.json"
    save_scenario(scenario, path)
    reloaded = load_scenario(path)
    # The dict form is a stable, comparable representation of the whole scenario.
    assert scenario_to_dict(reloaded) == scenario_to_dict(scenario)


def test_dict_round_trip_preserves_trade_and_credit_path() -> None:
    scenario = _sample()
    rebuilt = scenario_from_dict(scenario_to_dict(scenario))
    original_deal = scenario.deal_stream[0].trade
    rebuilt_deal = rebuilt.deal_stream[0].trade
    assert rebuilt_deal == original_deal  # frozen dataclass equality
    assert rebuilt.counterparty("CP001").credit_path[-1].internal_rating == "CCC"


# --------------------------------------------------------------------------- #
# End-to-end run
# --------------------------------------------------------------------------- #


def test_full_scenario_runs_end_to_end() -> None:
    scenario = _sample()
    decisions = {ACME_DEAL: _approve(ACME_DEAL), GLOBEX_DEAL: _approve(GLOBEX_DEAL)}
    result = run_scenario(scenario, decisions)

    # One decision outcome per arriving deal, both accepted.
    assert len(result.decisions) == 2
    assert all(o.accepted for o in result.decisions)
    by_trade = {o.trade_id: o for o in result.decisions}
    assert by_trade[ACME_DEAL].round == 0
    assert by_trade[GLOBEX_DEAL].round == 1
    # Headline analytics are populated (not NaN) and non-negative.
    assert by_trade[ACME_DEAL].peak_pfe > 0.0
    assert by_trade[ACME_DEAL].cva >= 0.0

    # Exactly one default outcome (Acme in round 2); Globex never defaults.
    assert len(result.defaults) == 1
    dflt = result.defaults[0]
    assert dflt.counterparty_id == "CP001"
    assert dflt.round == 2
    assert dflt.n_open_trades == 1
    assert result.total_realized_loss == pytest.approx(dflt.realized_loss)


def test_scenario_is_reproducible() -> None:
    scenario = _sample()
    decisions = {ACME_DEAL: _approve(ACME_DEAL), GLOBEX_DEAL: _approve(GLOBEX_DEAL)}
    a = run_scenario(scenario, decisions)
    b = run_scenario(scenario, decisions)
    assert a.total_realized_loss == b.total_realized_loss
    assert a.decisions[0].peak_pfe == b.decisions[0].peak_pfe


# --------------------------------------------------------------------------- #
# Realized-loss consequence of the collateral decision
# --------------------------------------------------------------------------- #


def test_undercollateralized_approval_loses_at_default() -> None:
    scenario = _sample()
    decisions = {ACME_DEAL: _approve(ACME_DEAL, require_collateral=False)}
    result = run_scenario(scenario, decisions)
    dflt = result.defaults[0]

    recovery = scenario.counterparty("CP001").recovery_rate
    assert dflt.exposure_at_default > 0.0
    assert dflt.collateral_held == pytest.approx(0.0)
    # Loss is LGD times the uncollateralized exposure at default.
    assert dflt.realized_loss == pytest.approx(
        (1.0 - recovery) * dflt.exposure_at_default
    )
    assert dflt.realized_loss > 0.0


def test_wellcollateralized_approval_avoids_loss_at_default() -> None:
    scenario = _sample()
    decisions = {
        ACME_DEAL: Decision(
            trade_id=ACME_DEAL,
            action=DecisionAction.CONDITION,
            require_collateral=True,
            csa_threshold=0.0,
        )
    }
    result = run_scenario(scenario, decisions)
    dflt = result.defaults[0]

    # Same exposure as the under-collateralized case, but the CSA covers it.
    assert dflt.exposure_at_default > 0.0
    assert dflt.collateral_held == pytest.approx(dflt.exposure_at_default)
    assert dflt.realized_loss == pytest.approx(0.0)


def test_collateral_decision_is_the_only_difference_in_loss() -> None:
    scenario = _sample()
    under = run_scenario(scenario, {ACME_DEAL: _approve(ACME_DEAL)}).defaults[0]
    well = run_scenario(
        scenario,
        {
            ACME_DEAL: Decision(
                trade_id=ACME_DEAL,
                action=DecisionAction.APPROVE,
                require_collateral=True,
                csa_threshold=0.0,
            )
        },
    ).defaults[0]
    # Identical exposure at default; the collateral decision alone changes the loss.
    assert well.exposure_at_default == pytest.approx(under.exposure_at_default)
    assert under.realized_loss > well.realized_loss
    assert well.realized_loss == pytest.approx(0.0)


def test_declined_deal_leaves_no_book_and_no_loss() -> None:
    scenario = _sample()
    decisions = {ACME_DEAL: Decision(trade_id=ACME_DEAL, action=DecisionAction.DECLINE)}
    result = run_scenario(scenario, decisions)
    acme_decision = next(o for o in result.decisions if o.trade_id == ACME_DEAL)
    assert acme_decision.accepted is False
    dflt = result.defaults[0]
    assert dflt.n_open_trades == 0
    assert dflt.realized_loss == pytest.approx(0.0)


def test_missing_decision_defaults_to_decline() -> None:
    scenario = _sample()
    # No decisions supplied at all: every deal is declined.
    result = run_scenario(scenario, {})
    assert all(o.accepted is False for o in result.decisions)
    assert result.total_realized_loss == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# Validation and error handling
# --------------------------------------------------------------------------- #


def test_deal_referencing_unknown_counterparty_is_rejected() -> None:
    raw = scenario_to_dict(_sample())
    raw["deal_stream"][0]["trade"]["counterparty_id"] = "NOPE"
    with pytest.raises(ScenarioValidationError, match="unknown counterparty"):
        scenario_from_dict(raw)


def test_round_out_of_range_is_rejected() -> None:
    raw = scenario_to_dict(_sample())
    raw["defaults"][0]["round"] = 99
    with pytest.raises(ScenarioValidationError, match="out of range"):
        scenario_from_dict(raw)


def test_missing_file_raises_scenario_error(tmp_path) -> None:
    with pytest.raises(ScenarioError, match="not found"):
        load_scenario(tmp_path / "does_not_exist.json")


def test_malformed_json_raises_scenario_error(tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{ not valid json ", encoding="utf-8")
    with pytest.raises(ScenarioError, match="invalid JSON"):
        load_scenario(bad)


def test_unknown_product_is_rejected(tmp_path) -> None:
    raw = scenario_to_dict(_sample())
    raw["deal_stream"][0]["trade"]["product"] = "Warrant"
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ScenarioValidationError, match="product"):
        load_scenario(path)
