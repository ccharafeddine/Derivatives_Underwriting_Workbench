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
    #: Whether each deal also reports DV01 / CS01 / FX delta. Off by default
    #: because finite-difference sensitivities re-run the whole pipeline once per
    #: bumped risk factor (see :func:`~duw.risk.sensitivities.compute_sensitivities`),
    #: so a scenario that asks for them costs roughly four runs per deal instead
    #: of one. Only the stage that teaches sensitivities turns this on, and it
    #: pairs the flag with a smaller ``n_paths`` to stay responsive.
    compute_sensitivities: bool = False


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

    ``credit_limit`` is the limit a credit committee has approved for this name.
    When set it overrides whatever limit the learner picks, which is what makes a
    limit teachable at all: on a real desk the underwriter works *inside* a limit
    somebody else granted, so a scenario that lets the learner raise their own
    limit to clear a breach teaches nothing. Leave it ``None`` for the
    learner-chosen limit used by the introductory scenarios.
    """

    counterparty: Counterparty
    recovery_rate: float = 0.4
    credit_path: tuple[CreditState, ...] = ()
    credit_limit: float | None = None

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
class Prediction:
    """A predict-then-reveal question asked before the consequences are shown.

    Active recall beats being told: in guided mode the learner commits to an
    answer about what the numbers will do *before* the analytics are revealed,
    which turns a passive read of the consequence panel into a checked belief.
    ``options`` are the choices in display order and ``correct_index`` indexes
    into it; ``explanation`` is shown once an answer is given, whether right or
    wrong.
    """

    prompt: str
    options: tuple[str, ...]
    correct_index: int
    explanation: str = ""

    def __post_init__(self) -> None:
        if len(self.options) < 2:
            raise ValueError("a prediction needs at least two options")
        if not 0 <= self.correct_index < len(self.options):
            raise ValueError(
                f"correct_index {self.correct_index} out of range for "
                f"{len(self.options)} options"
            )

    def is_correct(self, index: int) -> bool:
        """Whether the option at ``index`` is the correct answer."""
        return index == self.correct_index


@dataclass(frozen=True)
class DealArrival:
    """A proposed trade arriving in a given round for the learner to assess.

    ``coaching`` is optional plain-English guidance shown before the decision in
    the simulator's guided mode (what to weigh on this deal). ``recommended`` is
    the model-author's ideal :class:`Decision` for this deal; the guided mode can
    apply it for the learner to follow along, and the run of all recommended
    decisions defines the "best play" benchmark the learner is scored against.
    ``prediction`` is an optional predict-then-reveal question gating the
    consequence panel in guided mode. All three are absent on a plain
    (non-tutorial) deal.
    """

    round: int
    trade: Trade
    coaching: str = ""
    recommended: Decision | None = None
    prediction: Prediction | None = None

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

    The trailing fields carry the *evidence behind* those headlines so the
    simulator can show the learner what an underwriter actually reads before
    deciding, rather than asserting who is risky: the counterparty's assessed
    credit (``internal_grade`` through ``cds_spread_5y``), the shape of the
    exposure over time (``time_grid`` / ``ee`` / ``pfe_95`` /
    ``ee_collateralized``), and how much of the exposure this trade *added* to an
    existing book (``existing_peak_pfe`` / ``incremental_peak_pfe`` /
    ``headroom``). All default to empty so an outcome can still be built without
    them; the engine populates them from the same pipeline run, at no extra cost.

    The collateral-mechanics and funding fields come from that same run and are
    likewise free. The sensitivities are the one exception: they cost extra
    pipeline runs and stay ``None`` unless the scenario opts in via
    :attr:`SimSettings.compute_sensitivities`.
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
    # -- counterparty credit evidence (Step 2 of the pipeline) --------------- #
    internal_grade: str | None = None
    merton_pd: float | None = None
    distance_to_default: float | None = None
    altman_z: float | None = None
    altman_zone: str | None = None
    #: CDS 5-year par spread for the counterparty's issuer this round, decimal.
    cds_spread_5y: float | None = None
    # -- exposure shape (Steps 6-7) ----------------------------------------- #
    time_grid: tuple[float, ...] = ()
    ee: tuple[float, ...] = ()
    pfe_95: tuple[float, ...] = ()
    ee_collateralized: tuple[float, ...] = ()
    # -- netting / limit detail (Step 9) ------------------------------------ #
    existing_peak_pfe: float = float("nan")
    incremental_peak_pfe: float = float("nan")
    headroom: float = float("nan")
    # -- collateral mechanics (Step 7) -------------------------------------- #
    #: Peak PFE before the CSA is applied, kept alongside the collateralized
    #: figure so the learner can read the *benefit* of the terms they set rather
    #: than only the residual. Equal to ``peak_pfe`` when no CSA is in force.
    uncollateralized_peak_pfe: float = float("nan")
    #: Margin period of risk actually applied, in business days. Surfaced because
    #: it is the one CSA term whose effect is invisible in the headline exposure:
    #: a longer MPoR leaves more of the gap uncovered even at a zero threshold.
    mpor_days: int = 0
    # -- funding (Step 8) ---------------------------------------------------- #
    #: Funding valuation adjustment on the net uncollateralized exposure. Zero
    #: when the scenario's ``funding_spread`` is zero, which is the default.
    fva: float = float("nan")
    # -- sensitivities (optional; see SimSettings.compute_sensitivities) ------ #
    #: All ``None`` unless the scenario opts into sensitivities, so a stage that
    #: does not teach them pays nothing for the fields.
    dv01_pfe: float | None = None
    dv01_cva: float | None = None
    cs01_cva: float | None = None
    fx_delta_pfe: float | None = None
    fx_delta_cva: float | None = None


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
