"""Headless scenario engine for the role-play underwriting simulator.

Steps through a :class:`~duw.scenario.model.Scenario` round by round. In each
round it advances the clock, builds that round's market state (the systemic
shock composed with each counterparty's idiosyncratic credit trajectory),
presents the deals arriving that round, takes a :class:`Decision`, and runs the
deal through the **existing** pipeline orchestrator against that state — it does
not reimplement pricing, exposure, or CVA. Accepted trades accumulate in a
per-counterparty book. When a scripted default fires, it reprices that
counterparty's open approved book at the round's state (via the existing
:class:`~duw.risk.exposure.ExposureEngine`), applies the governing CSA (via the
existing :func:`~duw.risk.collateral.apply_csa`), and records the realized loss.

No scoring or P&L attribution lives here — that is a later session; this engine
only records the raw consequences. No Qt imports; fully headless.

Realized-loss model (closeout at default): the loss on a defaulting
counterparty is ``(1 - recovery) * max(current_exposure - collateral_held, 0)``
where ``current_exposure`` is the positive spot net MtM of the open approved
trades at the round's market state and ``collateral_held`` is what the governing
CSA covers. This is the standard closeout loss net of collateral and recovery;
forward-looking margin-period-of-risk gap risk is surfaced in the per-decision
exposure / collateral analytics, not re-simulated at the instant of default.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace

import numpy as np

from duw.data.loader import load_market_snapshot
from duw.domain.counterparty import Counterparty
from duw.domain.instruments import NettingSet
from duw.domain.market import CreditCurve, MarketSnapshot
from duw.pipeline.orchestrator import RunConfig, run_pipeline
from duw.risk.collateral import CSA, apply_csa
from duw.risk.exposure import ExposureEngine
from duw.risk.scenarios import apply_scenario
from duw.scenario.model import (
    CreditState,
    DealArrival,
    Decision,
    DecisionAction,
    DecisionOutcome,
    DefaultOutcome,
    Scenario,
    ScenarioCounterparty,
    ScenarioResult,
)

# A threshold large enough that no collateral is ever called (an "open" CSA).
_OPEN_THRESHOLD = 1e15

# The current (spot) net MtM at t=0 is deterministic across Monte Carlo paths
# (all paths share the initial market state), so a single path reprices it
# exactly. See ExposureEngine / collateral.apply_csa, which rely on the same.
_DEFAULT_LOSS_PATHS = 1

# A decision provider is either a mapping keyed by trade id, or a callable that
# is asked for a decision when a deal arrives.
DecisionProvider = Mapping[str, Decision] | Callable[[DealArrival], Decision]


class ScenarioEngine:
    """Runs a scripted scenario end to end against the existing pipeline."""

    def __init__(
        self, scenario: Scenario, base_snapshot: MarketSnapshot | None = None
    ) -> None:
        self.scenario = scenario
        self.base_snapshot = base_snapshot or load_market_snapshot()
        # Per-counterparty running book of accepted trades and governing CSA.
        self._book: dict[str, NettingSet] = {
            cp.counterparty_id: NettingSet(
                netting_set_id=f"NS-{cp.counterparty_id}",
                counterparty_id=cp.counterparty_id,
            )
            for cp in scenario.counterparties
        }
        self._governing_csa: dict[str, CSA] = {}

    def run(self, decisions: DecisionProvider) -> ScenarioResult:
        """Step through every round and return the recorded outcomes.

        ``decisions`` supplies the learner's verdict on each deal: either a
        mapping from trade id to :class:`Decision`, or a callable given the
        :class:`DealArrival`. A deal with no supplied decision defaults to a
        decline.
        """
        decision_outcomes: list[DecisionOutcome] = []
        default_outcomes: list[DefaultOutcome] = []

        for rnd in range(self.scenario.meta.n_rounds):
            # Deals arriving this round are assessed and decided first.
            for arrival in self.scenario.deals_at(rnd):
                decision = self._resolve_decision(decisions, arrival)
                decision_outcomes.append(self._process_deal(rnd, arrival, decision))
            # Then any scripted defaults fire, closing out the open book.
            for event in self.scenario.defaults_at(rnd):
                cp = self.scenario.counterparty(event.counterparty_id)
                default_outcomes.append(self._process_default(rnd, cp))

        total_loss = sum(o.realized_loss for o in default_outcomes)
        return ScenarioResult(
            decisions=tuple(decision_outcomes),
            defaults=tuple(default_outcomes),
            total_realized_loss=total_loss,
        )

    # -- deal handling ----------------------------------------------------- #
    def _process_deal(
        self, rnd: int, arrival: DealArrival, decision: Decision
    ) -> DecisionOutcome:
        cp = self.scenario.counterparty(arrival.counterparty_id)
        state = self.scenario.credit_state_at(cp.counterparty_id, rnd)
        snapshot = self._round_snapshot(cp, rnd, state)
        counterparty = self._counterparty_for(cp, state)
        existing = self._book[cp.counterparty_id]

        config = self._run_config(decision)
        results = run_pipeline(
            counterparty,
            existing,
            arrival.trade,
            config,
            snapshot=snapshot,
        )

        if decision.accepted:
            self._book[cp.counterparty_id] = existing.add_trade(arrival.trade)
            self._governing_csa[cp.counterparty_id] = self._csa_from_decision(decision)

        exposure = results.exposure
        collateral = results.collateral
        cva = results.cva
        limits = results.limits
        memo = results.memo
        return DecisionOutcome(
            round=rnd,
            trade_id=arrival.trade_id,
            counterparty_id=cp.counterparty_id,
            action=decision.action,
            accepted=decision.accepted,
            recommendation=memo.recommendation if memo is not None else None,
            peak_pfe=float(exposure.peak_pfe) if exposure is not None else float("nan"),
            epe=float(exposure.epe) if exposure is not None else float("nan"),
            collateralized_peak_pfe=(
                float(collateral.peak_pfe_collateralized)
                if collateral is not None
                else float("nan")
            ),
            cva=float(cva.cva) if cva is not None else float("nan"),
            dva=float(cva.dva) if cva is not None else float("nan"),
            bcva=float(cva.bcva) if cva is not None else float("nan"),
            limit_utilization=(
                float(limits.utilization) if limits is not None else float("nan")
            ),
            limit_breach=bool(limits.breach) if limits is not None else False,
        )

    # -- default handling -------------------------------------------------- #
    def _process_default(self, rnd: int, cp: ScenarioCounterparty) -> DefaultOutcome:
        book = self._book[cp.counterparty_id]
        n_open = len(book.trades)
        if n_open == 0:
            outcome = DefaultOutcome(
                round=rnd,
                counterparty_id=cp.counterparty_id,
                n_open_trades=0,
                exposure_at_default=0.0,
                collateral_held=0.0,
                recovery_rate=cp.recovery_rate,
                realized_loss=0.0,
            )
            return outcome

        state = self.scenario.credit_state_at(cp.counterparty_id, rnd)
        snapshot = self._round_snapshot(cp, rnd, state)
        settings = self.scenario.settings
        engine = ExposureEngine(
            book,
            snapshot,
            kappa_rate=settings.kappa_rate,
            kappa_credit=settings.kappa_credit,
            credit_vol=settings.credit_vol,
        )
        grid = engine.build_time_grid(settings.n_steps)
        cube = engine.simulate_cube(
            grid, n_paths=_DEFAULT_LOSS_PATHS, seed=settings.seed
        )

        # The t=0 column is the deterministic current net MtM of the book.
        current_mtm = float(cube[:, 0].mean())
        exposure_at_default = max(current_mtm, 0.0)

        csa = self._governing_csa.get(
            cp.counterparty_id, CSA(threshold=_OPEN_THRESHOLD)
        )
        residual = float(np.maximum(apply_csa(cube, grid, csa)[:, 0], 0.0).mean())
        collateral_held = max(exposure_at_default - residual, 0.0)
        realized_loss = (1.0 - cp.recovery_rate) * residual

        # The counterparty has defaulted: its book is closed out.
        self._book[cp.counterparty_id] = NettingSet(
            netting_set_id=book.netting_set_id,
            counterparty_id=cp.counterparty_id,
        )
        return DefaultOutcome(
            round=rnd,
            counterparty_id=cp.counterparty_id,
            n_open_trades=n_open,
            exposure_at_default=exposure_at_default,
            collateral_held=collateral_held,
            recovery_rate=cp.recovery_rate,
            realized_loss=realized_loss,
        )

    # -- state builders ---------------------------------------------------- #
    def _round_snapshot(
        self, cp: ScenarioCounterparty, rnd: int, state: CreditState | None
    ) -> MarketSnapshot:
        """Market state for one counterparty in one round.

        The systemic market shock for the round is applied first, then the
        counterparty's idiosyncratic credit multiplier scales its own CDS curve
        on top (only when it has a traded issuer curve to scale).
        """
        snapshot = apply_scenario(self.base_snapshot, self.scenario.market_at(rnd))
        issuer = cp.counterparty.cds_issuer
        if (
            state is not None
            and state.spread_multiplier != 1.0
            and issuer is not None
            and issuer in snapshot.credit_curves
        ):
            snapshot = _scale_issuer_credit(snapshot, issuer, state.spread_multiplier)
        return snapshot

    @staticmethod
    def _counterparty_for(
        cp: ScenarioCounterparty, state: CreditState | None
    ) -> Counterparty:
        """The counterparty for this round, with any scripted rating override."""
        if state is not None and state.internal_rating is not None:
            return replace(cp.counterparty, internal_rating=state.internal_rating)
        return cp.counterparty

    def _run_config(self, decision: Decision) -> RunConfig:
        s = self.scenario.settings
        return RunConfig(
            seed=s.seed,
            n_paths=s.n_paths,
            n_steps=s.n_steps,
            horizon=s.horizon,
            lgd=s.lgd,
            own_credit_spread=s.own_credit_spread,
            own_recovery=s.own_recovery,
            funding_spread=s.funding_spread,
            wwr_correlation=s.wwr_correlation,
            kappa_rate=s.kappa_rate,
            kappa_credit=s.kappa_credit,
            credit_vol=s.credit_vol,
            csa_threshold=(
                decision.csa_threshold if decision.require_collateral else None
            ),
            csa_mta=decision.csa_mta,
            csa_initial_margin=decision.csa_initial_margin,
            csa_mpor_days=decision.csa_mpor_days,
            limit=decision.limit,
        )

    @staticmethod
    def _csa_from_decision(decision: Decision) -> CSA:
        threshold = (
            decision.csa_threshold if decision.require_collateral else _OPEN_THRESHOLD
        )
        return CSA(
            threshold=threshold,
            mta=decision.csa_mta,
            initial_margin=decision.csa_initial_margin,
            mpor_days=decision.csa_mpor_days,
        )

    @staticmethod
    def _resolve_decision(
        decisions: DecisionProvider, arrival: DealArrival
    ) -> Decision:
        if callable(decisions):
            return decisions(arrival)
        decision = decisions.get(arrival.trade_id)
        if decision is None:
            return Decision(trade_id=arrival.trade_id, action=DecisionAction.DECLINE)
        return decision


def _scale_issuer_credit(
    snapshot: MarketSnapshot, issuer: str, multiplier: float
) -> MarketSnapshot:
    """Return a snapshot with one issuer's CDS spreads scaled by ``multiplier``."""
    base = snapshot.credit_curves[issuer]
    scaled = CreditCurve(
        issuer=base.issuer,
        tenors=base.tenors,
        spreads=tuple(max(s * multiplier, 1e-6) for s in base.spreads),
        recovery_rate=base.recovery_rate,
    )
    credit_curves = dict(snapshot.credit_curves)
    credit_curves[issuer] = scaled
    return MarketSnapshot(
        as_of=snapshot.as_of,
        discount_curves=dict(snapshot.discount_curves),
        fx_spot=dict(snapshot.fx_spot),
        credit_curves=credit_curves,
        rate_vols=dict(snapshot.rate_vols),
        fx_vols=dict(snapshot.fx_vols),
    )


def run_scenario(
    scenario: Scenario,
    decisions: DecisionProvider,
    base_snapshot: MarketSnapshot | None = None,
) -> ScenarioResult:
    """Convenience wrapper: build a :class:`ScenarioEngine` and run it once."""
    return ScenarioEngine(scenario, base_snapshot=base_snapshot).run(decisions)
