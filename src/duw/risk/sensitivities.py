"""Exposure and CVA sensitivities by finite difference.

Estimates how the headline risk numbers move for a small market bump, by
re-running the pipeline against a bumped snapshot and differencing:

- **DV01** — change in peak PFE and CVA for a +1bp parallel shift of every zero
  curve.
- **CS01** — change in CVA for a +1bp (absolute) widening of every credit spread.
- **FX delta** — change in peak PFE and CVA for a +1% move of every FX spot.

Every run reuses the same Monte Carlo seed (``config.seed``), so the base and
bumped runs share their random draws (common random numbers) and the difference
reflects the market bump rather than simulation noise. Results are per-unit-bump
(per 1bp, per 1%). This is a one-sided finite-difference estimate; peak PFE is a
max of a percentile and can be mildly non-smooth, so treat the figures as
indicative.

Pure numerics; no Qt. Composes the orchestrator and the scenario shocks.
"""

from __future__ import annotations

from dataclasses import dataclass

from duw.domain.counterparty import Counterparty
from duw.domain.instruments import NettingSet, Trade
from duw.domain.market import CreditCurve, MarketSnapshot
from duw.domain.results import AnalysisResults
from duw.pipeline.orchestrator import RunConfig, run_pipeline
from duw.risk.scenarios import ScenarioSpec, apply_scenario

_BPS = 1e-4


@dataclass(frozen=True)
class Sensitivities:
    """Finite-difference sensitivities, each per unit bump."""

    dv01_pfe: float  # d(peak PFE) per +1bp parallel rates
    dv01_cva: float  # d(CVA) per +1bp parallel rates
    cs01_cva: float  # d(CVA) per +1bp credit spreads
    fx_delta_pfe: float  # d(peak PFE) per +1% FX
    fx_delta_cva: float  # d(CVA) per +1% FX
    rate_bump_bps: float
    spread_bump_bps: float
    fx_bump_pct: float


def _bump_credit_spreads(snapshot: MarketSnapshot, bps: float) -> MarketSnapshot:
    """Return a snapshot with every credit spread widened by ``bps`` absolutely."""
    delta = bps * _BPS
    return MarketSnapshot(
        as_of=snapshot.as_of,
        discount_curves=dict(snapshot.discount_curves),
        fx_spot=dict(snapshot.fx_spot),
        credit_curves={
            issuer: CreditCurve(
                issuer=curve.issuer,
                tenors=curve.tenors,
                spreads=tuple(max(s + delta, 1e-6) for s in curve.spreads),
                recovery_rate=curve.recovery_rate,
            )
            for issuer, curve in snapshot.credit_curves.items()
        },
        rate_vols=dict(snapshot.rate_vols),
        fx_vols=dict(snapshot.fx_vols),
    )


def compute_sensitivities(
    counterparty: Counterparty,
    netting_set: NettingSet,
    proposed_trade: Trade,
    config: RunConfig,
    snapshot: MarketSnapshot,
    *,
    rate_bump_bps: float = 1.0,
    spread_bump_bps: float = 1.0,
    fx_bump_pct: float = 1.0,
) -> Sensitivities:
    """Bump-and-reprice sensitivities of peak PFE and CVA (common random numbers)."""

    def run(snap: MarketSnapshot) -> AnalysisResults:
        return run_pipeline(
            counterparty, netting_set, proposed_trade, config, snapshot=snap
        )

    base = run(snapshot)
    rate = run(
        apply_scenario(
            snapshot, ScenarioSpec(name="dv01", rate_shift_bps=rate_bump_bps)
        )
    )
    spread = run(_bump_credit_spreads(snapshot, spread_bump_bps))
    fx = run(
        apply_scenario(snapshot, ScenarioSpec(name="fxdelta", fx_shock_pct=fx_bump_pct))
    )

    base_pfe = base.exposure.peak_pfe
    base_cva = base.cva.cva

    def d_pfe(result: AnalysisResults) -> float:
        return result.exposure.peak_pfe - base_pfe

    def d_cva(result: AnalysisResults) -> float:
        return result.cva.cva - base_cva

    return Sensitivities(
        dv01_pfe=d_pfe(rate) / rate_bump_bps,
        dv01_cva=d_cva(rate) / rate_bump_bps,
        cs01_cva=d_cva(spread) / spread_bump_bps,
        fx_delta_pfe=d_pfe(fx) / fx_bump_pct,
        fx_delta_cva=d_cva(fx) / fx_bump_pct,
        rate_bump_bps=rate_bump_bps,
        spread_bump_bps=spread_bump_bps,
        fx_bump_pct=fx_bump_pct,
    )
