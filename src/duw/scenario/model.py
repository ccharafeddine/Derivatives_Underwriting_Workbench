"""Scenario data model for the role-play underwriting simulator.

Frozen dataclasses describing a scripted, multi-round underwriting scenario: who
the counterparties are and how their credit deteriorates round by round, how the
market moves each round, which deals arrive when, and which counterparties
default and when. Plus the learner's :class:`Decision` on each deal and the
per-round outcome records the engine produces.

This is the shared backbone the future simulator UI and instructor mode both sit
on. Pure data; **no Qt imports** and no pricing/exposure/CVA logic — the engine
(:mod:`duw.scenario.engine`) orchestrates the existing pipeline against this
model; it does not reimplement any of it.

Unit conventions (consistent with the rest of the app):

- Money amounts are in the trade / netting-set currency.
- ``spread_multiplier`` scales a counterparty's CDS spreads relative to the base
  snapshot (``1.0`` == unchanged, ``2.0`` == spreads doubled).
- ``recovery_rate`` is a decimal in ``[0, 1]``; loss given default is
  ``1 - recovery_rate``.
- Rounds are zero-based indices in ``[0, meta.n_rounds)``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from duw.domain.counterparty import Counterparty
from duw.domain.instruments import Trade
from duw.risk.scenarios import ScenarioSpec


class DecisionAction(StrEnum):
    """The learner's verdict on a proposed deal.

    ``APPROVE`` and ``CONDITION`` both accept the trade into the book (a
    conditional approval is an approval subject to collateral / limit terms);
    ``DECLINE`` turns it away, so it never enters the netting set.
    """

    APPROVE = "approve"
    DECLINE = "decline"
    CONDITION = "condition"


# ---------------------------------------------------------------------------
# Simulation settings and the learner's decision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SimSettings:
    """Monte Carlo and credit settings shared by every round of a scenario.

    These mirror the reproducibility inputs of ``pipeline.orchestrator.RunConfig``
    that are stable across rounds; the per-round CSA and limit come from each
    :class:`Decision` instead. A fixed ``seed`` keeps the whole scenario
    reproducible.
    """

    seed: int = 12345
    n_paths: int = 2000
    n_steps: int = 12
    horizon: float = 1.0
    lgd: float = 0.6
    own_credit_spread: float = 0.004
    own_recovery: float = 0.4
    funding_spread: float = 0.0
    wwr_correlation: float = 0.0
    kappa_rate: float = 0.10
    kappa_credit: float = 0.30
    credit_vol: float = 0.50


@dataclass(frozen=True)
class Decision:
    """The learner's decision on one proposed deal.

    When ``require_collateral`` is False the trade is left uncollateralized
    (equivalent to no CSA); when True the CSA terms below apply. ``limit`` is the
    per-counterparty PFE limit the trade is checked against. The CSA terms and
    limit are recorded as the governing terms of the counterparty relationship
    when the deal is accepted.
    """

    trade_id: str
    action: DecisionAction
    require_collateral: bool = False
    csa_threshold: float = 0.0
    csa_mta: float = 0.0
    csa_initial_margin: float = 0.0
    csa_mpor_days: int = 10
    limit: float = 5_000_000.0

    @property
    def accepted(self) -> bool:
        """Whether this decision brings the trade into the book."""
        return self.action in (DecisionAction.APPROVE, DecisionAction.CONDITION)


# ---------------------------------------------------------------------------
# Scenario structure
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScenarioMeta:
    """Human-facing description of a scenario.

    The ``tutorial`` flag and ``intro`` / ``outro`` narration drive the
    simulator's guided (coached) mode: when ``tutorial`` is True the UI turns on
    coaching automatically, opens with ``intro`` and closes with ``outro``. All
    three are optional so a plain scenario carries none of them.
    """

    title: str
    description: str
    n_rounds: int
    learning_objectives: tuple[str, ...] = ()
    tutorial: bool = False
    intro: str = ""
    outro: str = ""


@dataclass(frozen=True)
class CreditState:
    """A counterparty's idiosyncratic credit in one round.

    ``spread_multiplier`` scales that counterparty's CDS curve relative to the
    base snapshot for this round (applied on top of any systemic market move in
    the round's :class:`~duw.risk.scenarios.ScenarioSpec`). ``internal_rating``
    optionally overrides the seeded grade, e.g. to script a downgrade. A default
    event is expressed separately via :class:`DefaultEvent`.
    """

    round: int
    spread_multiplier: float = 1.0
    internal_rating: str | None = None


@dataclass(frozen=True)
class ScenarioCounterparty:
    """A counterparty in the scenario, with a scripted credit trajectory.

    The :class:`~duw.domain.counterparty.Counterparty` is embedded in full so a
    scenario file is self-contained and shareable. ``credit_path`` gives the
    idiosyncratic credit state per round (rounds without an entry keep the base
    credit). ``recovery_rate`` is used when the counterparty defaults.
    """

    counterparty: Counterparty
    recovery_rate: float = 0.4
    credit_path: tuple[CreditState, ...] = ()

    @property
    def counterparty_id(self) -> str:
        return self.counterparty.counterparty_id

    def state_at(self, round_index: int) -> CreditState | None:
        """Return the credit state scripted for ``round_index``, if any."""
        for state in self.credit_path:
            if state.round == round_index:
                return state
        return None


@dataclass(frozen=True)
class MarketRound:
    """The systemic market move applied in one round, as a shock vs the base."""

    round: int
    spec: ScenarioSpec = field(default_factory=ScenarioSpec)


@dataclass(frozen=True)
class DealArrival:
    """A proposed trade arriving in a given round for the learner to assess.

    ``coaching`` is optional plain-English guidance shown before the decision in
    the simulator's guided mode (what to weigh on this deal). ``recommended`` is
    the model-author's ideal :class:`Decision` for this deal; the guided mode can
    apply it for the learner to follow along, and the run of all recommended
    decisions defines the "best play" benchmark the learner is scored against.
    Both are absent on a plain (non-tutorial) deal.
    """

    round: int
    trade: Trade
    coaching: str = ""
    recommended: Decision | None = None

    @property
    def trade_id(self) -> str:
        return self.trade.trade_id

    @property
    def counterparty_id(self) -> str:
        return self.trade.counterparty_id


@dataclass(frozen=True)
class DefaultEvent:
    """A scripted counterparty default firing at the end of a round.

    ``coaching`` is optional plain-English guidance shown on the default panel in
    guided mode, tying the loss (or its absence) back to the earlier decision.
    """

    round: int
    counterparty_id: str
    coaching: str = ""


@dataclass(frozen=True)
class Scenario:
    """A complete scripted underwriting scenario.

    ``settings`` fixes the Monte Carlo inputs shared across rounds so the whole
    scenario is reproducible. The helper accessors below are what the engine
    steps through round by round.
    """

    meta: ScenarioMeta
    counterparties: tuple[ScenarioCounterparty, ...]
    market_path: tuple[MarketRound, ...] = ()
    deal_stream: tuple[DealArrival, ...] = ()
    defaults: tuple[DefaultEvent, ...] = ()
    settings: SimSettings = field(default_factory=SimSettings)

    def counterparty(self, counterparty_id: str) -> ScenarioCounterparty:
        """Return the scenario counterparty with ``counterparty_id`` or raise."""
        for cp in self.counterparties:
            if cp.counterparty_id == counterparty_id:
                return cp
        raise KeyError(f"no counterparty {counterparty_id!r} in scenario")

    def deals_at(self, round_index: int) -> list[DealArrival]:
        """Deals arriving in ``round_index``, in declaration order."""
        return [d for d in self.deal_stream if d.round == round_index]

    def defaults_at(self, round_index: int) -> list[DefaultEvent]:
        """Default events firing in ``round_index``."""
        return [e for e in self.defaults if e.round == round_index]

    def market_at(self, round_index: int) -> ScenarioSpec:
        """Systemic market shock for ``round_index`` (base if none scripted)."""
        for m in self.market_path:
            if m.round == round_index:
                return m.spec
        return ScenarioSpec()

    def credit_state_at(
        self, counterparty_id: str, round_index: int
    ) -> CreditState | None:
        """Idiosyncratic credit state for a counterparty in a round, if any."""
        return self.counterparty(counterparty_id).state_at(round_index)


# ---------------------------------------------------------------------------
# Outcome records (produced by the engine)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DecisionOutcome:
    """What happened when a deal was assessed and decided in a round.

    The headline analytics are the same numbers the underwriting memo reports,
    lifted from the pipeline's ``AnalysisResults`` for the deal's netting set
    (existing book plus the proposed trade).
    """

    round: int
    trade_id: str
    counterparty_id: str
    action: DecisionAction
    accepted: bool
    recommendation: str | None
    peak_pfe: float
    epe: float
    collateralized_peak_pfe: float
    cva: float
    dva: float
    bcva: float
    limit_utilization: float
    limit_breach: bool


@dataclass(frozen=True)
class DefaultOutcome:
    """The realized consequence when a counterparty defaults.

    ``exposure_at_default`` is the positive current (spot) net MtM of the
    counterparty's open approved trades at the round's market state.
    ``collateral_held`` is the value the governing CSA covers; ``realized_loss``
    is ``(1 - recovery_rate)`` applied to the uncollateralized remainder.
    """

    round: int
    counterparty_id: str
    n_open_trades: int
    exposure_at_default: float
    collateral_held: float
    recovery_rate: float
    realized_loss: float


@dataclass(frozen=True)
class ScenarioResult:
    """The full record of running a scenario against a set of decisions."""

    decisions: tuple[DecisionOutcome, ...] = ()
    defaults: tuple[DefaultOutcome, ...] = ()
    total_realized_loss: float = 0.0

    def loss_for(self, counterparty_id: str) -> float:
        """Total realized default loss attributed to one counterparty."""
        return sum(
            d.realized_loss
            for d in self.defaults
            if d.counterparty_id == counterparty_id
        )
