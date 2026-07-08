"""Role-play underwriting simulator backbone.

The scripted, multi-round scenario engine the simulator UI and instructor mode
(both later sessions) sit on. Loads a shareable scenario file, steps through its
rounds against the existing underwriting pipeline, and records the consequences
of each decision — including realized loss when a counterparty defaults. No UI
and no scoring live here; this package is pure and headlessly testable.
"""

from __future__ import annotations

from duw.scenario.engine import ScenarioEngine, run_scenario
from duw.scenario.io import (
    ScenarioError,
    ScenarioValidationError,
    load_bundled_scenario,
    load_scenario,
    save_scenario,
    scenario_from_dict,
    scenario_to_dict,
    validate_scenario,
)
from duw.scenario.model import (
    CreditState,
    DealArrival,
    Decision,
    DecisionAction,
    DecisionOutcome,
    DefaultEvent,
    DefaultOutcome,
    MarketRound,
    Scenario,
    ScenarioCounterparty,
    ScenarioMeta,
    ScenarioResult,
    SimSettings,
)

__all__ = [
    "CreditState",
    "DealArrival",
    "Decision",
    "DecisionAction",
    "DecisionOutcome",
    "DefaultEvent",
    "DefaultOutcome",
    "MarketRound",
    "Scenario",
    "ScenarioCounterparty",
    "ScenarioEngine",
    "ScenarioError",
    "ScenarioMeta",
    "ScenarioResult",
    "ScenarioValidationError",
    "SimSettings",
    "load_bundled_scenario",
    "load_scenario",
    "run_scenario",
    "save_scenario",
    "scenario_from_dict",
    "scenario_to_dict",
    "validate_scenario",
]
