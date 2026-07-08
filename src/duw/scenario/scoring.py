"""Risk-adjusted scoring for a played scenario.

Turns a completed :class:`~duw.scenario.model.ScenarioResult` (the per-round
decision outcomes plus default events the engine records) into a
:class:`ScoreResult`: a raw P&L, a risk-adjusted score, and a component
breakdown the learner can read to see *why* they scored what they did.

The scoring captures the core tension of the underwriting desk:

- **Doing deals earns revenue** — an origination fee/spread plus the CVA charged
  to the client.
- **Defaults destroy it** — a realized loss when a counterparty defaults on an
  under-collateralized book.
- **Carrying exposure costs** — a per-round charge on the exposure retained after
  collateral, and a penalty for breaching a limit.
- **Caution concedes competitiveness** — demanding collateral gives up spread,
  and declining a deal forgoes its revenue entirely.

So neither extreme wins: recklessness is punished by exposure cost, the risk
adjustment, and (when a default lands) the loss; over-caution leaves revenue on
the table. The **risk-adjusted** score penalizes retained exposure and breaches
on top of raw P&L, so a player who wins on luck while running reckless exposure
does not top a well-collateralized one.

**This is a teaching abstraction of desk economics, not a real P&L attribution
model.** The fee, exposure, and risk charges are illustrative proxies (scaled off
the exposure the engine already computes), chosen to make the risk-versus-return
trade-off legible — not calibrated desk revenue or a capital model.

Time convention: a round is a discrete decision step, not a calendar increment.
Every cost and reward accrues per round, at the decision and default events the
engine records; there is no annualization, carry, or tenor aging here. Pure
numerics; **no Qt imports**.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from duw.scenario.model import DecisionOutcome, DefaultOutcome, ScenarioResult


@dataclass(frozen=True)
class ScoringParams:
    """Adjustable scoring assumptions (instructor mode will tune these).

    All rates are dimensionless multipliers applied to money amounts already in
    the netting-set currency, so every component below is a currency amount. The
    defaults are illustrative and deliberately gentle; they are the one place to
    change how the game rewards revenue versus punishes risk.

    Fee, concession, exposure cost, and the risk charge are all expressed on the
    same exposure basis — the deal's peak PFE — so their rates are directly
    comparable and the trade-off between them is transparent. In particular,
    leaving a deal uncollateralized earns the full fee but carries exposure and
    risk charges on the whole peak, while collateralizing it concedes spread but
    removes those charges; a survivor is best left open when
    ``collateral_concession_rate > exposure_cost_rate + risk_aversion``, and a
    name that defaults is best collateralized. Neither extreme dominates.

    - ``origination_fee_rate`` — fee earned per unit of a deal's (uncollateralized)
      peak PFE, a proxy for the spread scaled by deal size.
    - ``cva_collection_rate`` — fraction of the charged CVA actually booked as
      revenue (``1.0`` == the client pays the full CVA).
    - ``collateral_concession_rate`` — spread conceded per unit of exposure
      collateralized away (``peak_pfe`` minus ``collateralized_peak_pfe``); this
      is the competitiveness cost of demanding collateral.
    - ``exposure_cost_rate`` — per-round capital/funding charge per unit of the
      exposure retained after collateral (``collateralized_peak_pfe``).
    - ``breach_penalty`` — flat P&L penalty when an accepted deal breaches its
      limit.
    - ``risk_aversion`` — risk-adjusted charge per unit of retained exposure
      taken across the run (the "luck adjuster": it docks reckless exposure even
      when no default happens).
    - ``breach_risk_penalty`` — extra risk-adjusted penalty per limit breach.
    - ``recovery_rate`` — optional recovery override. When ``None`` (default) the
      engine's own ``realized_loss`` is used unchanged; when set, the loss is
      recomputed as ``(1 - recovery_rate)`` times the uncollateralized amount at
      default (``exposure_at_default - collateral_held``), letting an instructor
      stress the loss independently of the scenario's recovery.
    """

    origination_fee_rate: float = 0.040
    cva_collection_rate: float = 1.0
    collateral_concession_rate: float = 0.030
    exposure_cost_rate: float = 0.008
    breach_penalty: float = 250_000.0
    risk_aversion: float = 0.012
    breach_risk_penalty: float = 500_000.0
    recovery_rate: float | None = None


@dataclass(frozen=True)
class ScoreBreakdown:
    """The score's components, all as currency amounts (positive magnitudes).

    ``raw_pnl`` reconstructs exactly as
    ``revenue + cva_collected - realized_losses - exposure_cost - breach_penalty``.
    ``risk_penalty`` is the additional risk-adjustment charge subtracted from raw
    P&L to form the risk-adjusted score; it is not part of P&L.
    """

    revenue: float = 0.0
    cva_collected: float = 0.0
    realized_losses: float = 0.0
    exposure_cost: float = 0.0
    breach_penalty: float = 0.0
    risk_penalty: float = 0.0


@dataclass(frozen=True)
class RoundScore:
    """Per-round component breakdown, for a legible round-by-round view.

    ``net`` is the round's P&L contribution
    (``revenue + cva_collected - realized_losses - exposure_cost - breach_penalty``);
    the round nets sum to the run's ``raw_pnl``.
    """

    round: int
    revenue: float = 0.0
    cva_collected: float = 0.0
    realized_losses: float = 0.0
    exposure_cost: float = 0.0
    breach_penalty: float = 0.0

    @property
    def net(self) -> float:
        return (
            self.revenue
            + self.cva_collected
            - self.realized_losses
            - self.exposure_cost
            - self.breach_penalty
        )


@dataclass(frozen=True)
class ScoreResult:
    """The scored outcome of a played scenario."""

    raw_pnl: float
    risk_adjusted_score: float
    breakdown: ScoreBreakdown
    by_round: tuple[RoundScore, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Mutable per-round accumulator (internal to scoring)
# ---------------------------------------------------------------------------


@dataclass
class _RoundAccumulator:
    revenue: float = 0.0
    cva_collected: float = 0.0
    realized_losses: float = 0.0
    exposure_cost: float = 0.0
    breach_penalty: float = 0.0

    def to_round_score(self, round_index: int) -> RoundScore:
        return RoundScore(
            round=round_index,
            revenue=self.revenue,
            cva_collected=self.cva_collected,
            realized_losses=self.realized_losses,
            exposure_cost=self.exposure_cost,
            breach_penalty=self.breach_penalty,
        )


class Scorer:
    """Scores a :class:`ScenarioResult` into a :class:`ScoreResult`."""

    def __init__(self, params: ScoringParams | None = None) -> None:
        self.params = params or ScoringParams()

    def score(self, result: ScenarioResult) -> ScoreResult:
        """Compute the raw P&L, risk-adjusted score, and breakdown."""
        p = self.params
        rounds: dict[int, _RoundAccumulator] = {}
        retained_exposure_total = 0.0
        breach_count = 0

        def bucket(round_index: int) -> _RoundAccumulator:
            return rounds.setdefault(round_index, _RoundAccumulator())

        # Revenue and carrying costs accrue at each accepted decision.
        for outcome in result.decisions:
            if not outcome.accepted:
                continue
            acc = bucket(outcome.round)
            acc.revenue += self._deal_revenue(outcome)
            acc.cva_collected += p.cva_collection_rate * outcome.cva
            acc.exposure_cost += p.exposure_cost_rate * _retained(outcome)
            retained_exposure_total += _retained(outcome)
            if outcome.limit_breach:
                acc.breach_penalty += p.breach_penalty
                breach_count += 1

        # Realized losses accrue at each default event.
        for event in result.defaults:
            bucket(event.round).realized_losses += self._loss(event)

        by_round = tuple(rounds[r].to_round_score(r) for r in sorted(rounds))

        breakdown = ScoreBreakdown(
            revenue=sum(rs.revenue for rs in by_round),
            cva_collected=sum(rs.cva_collected for rs in by_round),
            realized_losses=sum(rs.realized_losses for rs in by_round),
            exposure_cost=sum(rs.exposure_cost for rs in by_round),
            breach_penalty=sum(rs.breach_penalty for rs in by_round),
            risk_penalty=(
                p.risk_aversion * retained_exposure_total
                + p.breach_risk_penalty * breach_count
            ),
        )
        raw_pnl = (
            breakdown.revenue
            + breakdown.cva_collected
            - breakdown.realized_losses
            - breakdown.exposure_cost
            - breakdown.breach_penalty
        )
        return ScoreResult(
            raw_pnl=raw_pnl,
            risk_adjusted_score=raw_pnl - breakdown.risk_penalty,
            breakdown=breakdown,
            by_round=by_round,
        )

    # -- component helpers ------------------------------------------------- #
    def _deal_revenue(self, outcome: DecisionOutcome) -> float:
        """Origination fee less the spread conceded for demanding collateral.

        The fee is charged on the deal's uncollateralized peak PFE (a size proxy
        independent of the collateral decision); the concession scales with how
        much exposure the collateral removes.
        """
        p = self.params
        fee = p.origination_fee_rate * max(outcome.peak_pfe, 0.0)
        collateralized_away = max(
            outcome.peak_pfe - outcome.collateralized_peak_pfe, 0.0
        )
        concession = p.collateral_concession_rate * collateralized_away
        return fee - concession

    def _loss(self, event: DefaultOutcome) -> float:
        """Realized-loss penalty for a default, honoring a recovery override."""
        if self.params.recovery_rate is None:
            return event.realized_loss
        uncollateralized = max(event.exposure_at_default - event.collateral_held, 0.0)
        return (1.0 - self.params.recovery_rate) * uncollateralized


def _retained(outcome: DecisionOutcome) -> float:
    """Exposure retained after collateral for an accepted deal (non-negative)."""
    return max(outcome.collateralized_peak_pfe, 0.0)


def score_scenario(
    result: ScenarioResult, params: ScoringParams | None = None
) -> ScoreResult:
    """Convenience wrapper: build a :class:`Scorer` and score one run."""
    return Scorer(params).score(result)
