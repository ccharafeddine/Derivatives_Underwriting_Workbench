"""Market scenario shocks for stress testing.

Applies a set of market shocks to a :class:`MarketSnapshot` and returns a new,
shocked snapshot that the pipeline can be re-run against, so a proposed trade's
exposure, CVA, and limit utilization can be compared base vs stressed.

Shocks (all applied together, each defaulting to no change):

- **rate_shift_bps** — a parallel shift added to every zero curve.
- **steepen_bps** — a curve twist: the shortest tenor moves by
  ``-steepen_bps/2`` and the longest by ``+steepen_bps/2``, linear in between
  (a positive value steepens, a negative value flattens).
- **fx_shock_pct** — a percentage move applied to every FX spot.
- **spread_widen_pct** — a percentage widening of every issuer's CDS spreads
  (e.g. ``50`` scales spreads by 1.5x).

Pure numerics; no Qt. This module has no pipeline dependency — compose it with
``run_pipeline(..., snapshot=apply_scenario(snap, spec))`` to run a stressed
pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass

from duw.domain.market import CreditCurve, MarketSnapshot, YieldCurve

_BPS = 1e-4


@dataclass(frozen=True)
class ScenarioSpec:
    """A named set of market shocks. All-zero shocks reproduce the base."""

    name: str = "Base"
    rate_shift_bps: float = 0.0
    steepen_bps: float = 0.0
    fx_shock_pct: float = 0.0
    spread_widen_pct: float = 0.0

    @property
    def is_base(self) -> bool:
        """Whether this scenario applies no shocks."""
        return (
            self.rate_shift_bps == 0.0
            and self.steepen_bps == 0.0
            and self.fx_shock_pct == 0.0
            and self.spread_widen_pct == 0.0
        )


def _twist(tenor: float, t_min: float, t_max: float, steepen_bps: float) -> float:
    """Linear twist in decimals: ``-steepen/2`` at ``t_min``, ``+steepen/2`` at ``t_max``."""
    if steepen_bps == 0.0 or t_max <= t_min:
        return 0.0
    frac = (tenor - t_min) / (t_max - t_min)  # 0 at short end, 1 at long end
    return (steepen_bps * _BPS) * (frac - 0.5)


def _shock_yield_curve(curve: YieldCurve, spec: ScenarioSpec) -> YieldCurve:
    t_min, t_max = curve.tenors[0], curve.tenors[-1]
    shift = spec.rate_shift_bps * _BPS
    zeros = tuple(
        r + shift + _twist(t, t_min, t_max, spec.steepen_bps)
        for t, r in zip(curve.tenors, curve.zero_rates, strict=True)
    )
    return YieldCurve(currency=curve.currency, tenors=curve.tenors, zero_rates=zeros)


def _shock_credit_curve(curve: CreditCurve, spec: ScenarioSpec) -> CreditCurve:
    factor = 1.0 + spec.spread_widen_pct / 100.0
    spreads = tuple(max(s * factor, 1e-6) for s in curve.spreads)
    return CreditCurve(
        issuer=curve.issuer,
        tenors=curve.tenors,
        spreads=spreads,
        recovery_rate=curve.recovery_rate,
    )


def apply_scenario(snapshot: MarketSnapshot, spec: ScenarioSpec) -> MarketSnapshot:
    """Return a new snapshot with ``spec``'s shocks applied.

    The base scenario (all-zero shocks) returns an equivalent snapshot.
    """
    if spec.is_base:
        return snapshot

    fx_factor = 1.0 + spec.fx_shock_pct / 100.0
    return MarketSnapshot(
        as_of=snapshot.as_of,
        discount_curves={
            ccy: _shock_yield_curve(curve, spec)
            for ccy, curve in snapshot.discount_curves.items()
        },
        fx_spot={pair: rate * fx_factor for pair, rate in snapshot.fx_spot.items()},
        credit_curves={
            issuer: _shock_credit_curve(curve, spec)
            for issuer, curve in snapshot.credit_curves.items()
        },
        rate_vols=dict(snapshot.rate_vols),
        fx_vols=dict(snapshot.fx_vols),
    )
