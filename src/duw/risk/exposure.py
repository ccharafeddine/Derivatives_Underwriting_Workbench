"""Monte Carlo exposure engine.

Given a netting set, a market snapshot, a time grid, and a path count, the
:class:`ExposureEngine` simulates the risk factors, reprices the netting set on
every path at every grid date into a net mark-to-market cube, takes the positive
part, and reads off the exposure profile: expected exposure ``EE(t)``, expected
positive exposure ``EPE``, potential future exposure ``PFE(t)`` at 95% and 99%,
peak PFE over the trade life, and the percentile cone.

Note that ``PFE(t, 95%) >= EE(t)`` is not universal: at nodes where the
in-the-money probability falls below 5% (e.g. a swap near maturity), the 95th
percentile of exposure is legitimately 0 while EE is a small positive number.
The dominance holds wherever exposure is reasonably likely.

Repricing along a path uses the shocked-curve approximation from
:mod:`duw.risk.simulators`: at node ``(path, t)`` the discount curve is the
initial curve shifted by the simulated parallel rate move, the survival curve is
bootstrapped from the initial CDS spreads scaled by the simulated credit
multiplier, and the FX spot is the simulated level. Each trade is then priced at
``valuation_time = t`` with the existing analytic pricers.

**Currency scope (v1):** exposure is aggregated in a single reporting currency.
IRS and CDS MtM are in their trade currency and FX-forward MtM is in its quote
currency; all are summed directly, which is exact when the netting set shares
one reporting currency (as the bundled seeds do). Cross-currency conversion of
MtM is a documented v1 simplification.

Pure numerics; no Qt.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from duw.domain.instruments import CDS, IRS, FXForward, NettingSet, Trade
from duw.domain.market import CreditCurve, MarketSnapshot
from duw.domain.results import ExposureProfile
from duw.pricing.cds import price_cds
from duw.pricing.curves import DiscountCurve, SurvivalCurve, year_fraction
from duw.pricing.fx_forward import forward_rate_fx, price_fx_forward
from duw.pricing.irs import price_irs


@dataclass(frozen=True)
class _CurveData:
    """Initial curve nodes for a currency, cached for fast shifted rebuilds."""

    tenors: tuple[float, ...]
    zero_rates: tuple[float, ...]


class ExposureEngine:
    """Reprices a netting set across Monte Carlo paths to an exposure profile."""

    def __init__(
        self,
        netting_set: NettingSet,
        snapshot: MarketSnapshot,
        *,
        kappa_rate: float = 0.10,
        kappa_credit: float = 0.30,
        credit_vol: float = 0.50,
    ) -> None:
        self.netting_set = netting_set
        self.snapshot = snapshot
        self.as_of: date = snapshot.as_of
        self.kappa_rate = kappa_rate
        self.kappa_credit = kappa_credit
        self.credit_vol = credit_vol

        self._currencies = self._collect_currencies()
        self._issuers = self._collect_issuers()
        self._fx_pairs = self._collect_fx_pairs()
        self._curve_data = {
            ccy: _CurveData(
                tenors=snapshot.curve(ccy).tenors,
                zero_rates=snapshot.curve(ccy).zero_rates,
            )
            for ccy in self._currencies
        }

    # -- setup helpers ----------------------------------------------------- #
    def _collect_currencies(self) -> tuple[str, ...]:
        ccys: dict[str, None] = {}
        for trade in self.netting_set.trades:
            if isinstance(trade, FXForward):
                ccys.setdefault(trade.base_currency, None)
                ccys.setdefault(trade.quote_currency, None)
            else:
                ccys.setdefault(trade.currency, None)
        return tuple(sorted(ccys))

    def _collect_issuers(self) -> tuple[str, ...]:
        issuers: dict[str, None] = {}
        for trade in self.netting_set.trades:
            if isinstance(trade, CDS):
                issuers.setdefault(trade.reference_entity, None)
        return tuple(sorted(issuers))

    def _collect_fx_pairs(self) -> tuple[str, ...]:
        pairs: dict[str, None] = {}
        for trade in self.netting_set.trades:
            if isinstance(trade, FXForward):
                pairs.setdefault(trade.base_currency + trade.quote_currency, None)
        return tuple(sorted(pairs))

    def build_time_grid(self, n_steps: int) -> tuple[float, ...]:
        """Uniform grid from 0 to the longest trade maturity (inclusive)."""
        if not self.netting_set.trades:
            return (0.0,)
        t_max = max(
            year_fraction(self.as_of, t.maturity_date) for t in self.netting_set.trades
        )
        return tuple(np.linspace(0.0, t_max, n_steps + 1))

    # -- simulation -------------------------------------------------------- #
    def simulate_cube(
        self,
        time_grid: tuple[float, ...],
        n_paths: int,
        seed: int,
    ) -> np.ndarray:
        """Return the net-MtM cube, shape ``(n_paths, len(time_grid))``."""
        from duw.risk.simulators import (
            simulate_credit_factor,
            simulate_fx_spot,
            simulate_rate_shift,
        )

        rng = np.random.default_rng(seed)
        grid = np.asarray(time_grid, dtype=float)

        # Rate shifts per currency (drawn in a fixed order for reproducibility).
        rate_paths: dict[str, np.ndarray] = {}
        for ccy in self._currencies:
            sigma = self.snapshot.rate_vols.get(ccy, 0.01)
            rate_paths[ccy] = simulate_rate_shift(
                rng, grid, sigma=sigma, n_paths=n_paths, kappa=self.kappa_rate
            )

        # Credit multipliers per issuer.
        credit_paths: dict[str, np.ndarray] = {}
        for issuer in self._issuers:
            credit_paths[issuer] = simulate_credit_factor(
                rng,
                grid,
                sigma=self.credit_vol,
                n_paths=n_paths,
                kappa=self.kappa_credit,
            )

        # FX spots per pair, with mean equal to the CIP forward at each node.
        fx_paths: dict[str, np.ndarray] = {}
        for pair in self._fx_pairs:
            base_ccy, quote_ccy = pair[:3], pair[3:]
            base0 = DiscountCurve.from_zero_rates(*self._curve_args(base_ccy, 0.0))
            quote0 = DiscountCurve.from_zero_rates(*self._curve_args(quote_ccy, 0.0))
            spot0 = self.snapshot.fx(pair)
            forwards = [forward_rate_fx(spot0, base0, quote0, t) for t in grid]
            sigma = self.snapshot.fx_vols.get(pair, 0.10)
            fx_paths[pair] = simulate_fx_spot(
                rng, grid, s0=spot0, forwards=forwards, sigma=sigma, n_paths=n_paths
            )

        cube = np.empty((n_paths, len(grid)), dtype=float)
        for k, t in enumerate(grid):
            for p in range(n_paths):
                curves = {
                    ccy: DiscountCurve.from_zero_rates(
                        *self._curve_args(ccy, rate_paths[ccy][p, k])
                    )
                    for ccy in self._currencies
                }
                survivals = {
                    issuer: self._survival_for(issuer, credit_paths[issuer][p, k])
                    for issuer in self._issuers
                }
                spots = {pair: fx_paths[pair][p, k] for pair in self._fx_pairs}
                cube[p, k] = self._net_mtm(float(t), curves, survivals, spots)
        return cube

    def _curve_args(
        self, ccy: str, shift: float
    ) -> tuple[tuple[float, ...], tuple[float, ...]]:
        data = self._curve_data[ccy]
        shifted = tuple(r + shift for r in data.zero_rates)
        return data.tenors, shifted

    def _survival_for(self, issuer: str, log_factor: float) -> SurvivalCurve:
        base = self.snapshot.credit(issuer)
        multiplier = float(np.exp(log_factor))
        scaled = CreditCurve(
            issuer=base.issuer,
            tenors=base.tenors,
            spreads=tuple(s * multiplier for s in base.spreads),
            recovery_rate=base.recovery_rate,
        )
        return SurvivalCurve.bootstrap(scaled)

    def _net_mtm(
        self,
        valuation_time: float,
        curves: dict[str, DiscountCurve],
        survivals: dict[str, SurvivalCurve],
        spots: dict[str, float],
    ) -> float:
        total = 0.0
        for trade in self.netting_set.trades:
            total += self._price(trade, valuation_time, curves, survivals, spots)
        return total

    def _price(
        self,
        trade: Trade,
        valuation_time: float,
        curves: dict[str, DiscountCurve],
        survivals: dict[str, SurvivalCurve],
        spots: dict[str, float],
    ) -> float:
        if isinstance(trade, IRS):
            return price_irs(trade, curves[trade.currency], self.as_of, valuation_time)
        if isinstance(trade, FXForward):
            pair = trade.base_currency + trade.quote_currency
            return price_fx_forward(
                trade,
                curves[trade.base_currency],
                curves[trade.quote_currency],
                spots[pair],
                self.as_of,
                valuation_time,
            )
        if isinstance(trade, CDS):
            return price_cds(
                trade,
                curves[trade.currency],
                survivals[trade.reference_entity],
                self.as_of,
                valuation_time,
            )
        raise TypeError(f"unsupported trade type: {type(trade).__name__}")

    # -- profile ----------------------------------------------------------- #
    def run(
        self,
        *,
        n_paths: int = 2000,
        seed: int = 12345,
        n_steps: int = 12,
        time_grid: tuple[float, ...] | None = None,
    ) -> ExposureProfile:
        """Simulate and return the exposure profile for the netting set."""
        grid = time_grid if time_grid is not None else self.build_time_grid(n_steps)
        cube = self.simulate_cube(grid, n_paths=n_paths, seed=seed)
        return self.profile_from_cube(cube, grid)

    @staticmethod
    def profile_from_cube(
        cube: np.ndarray, time_grid: tuple[float, ...]
    ) -> ExposureProfile:
        """Compute EE / EPE / PFE / peak PFE from a net-MtM cube."""
        grid = np.asarray(time_grid, dtype=float)
        exposure = np.maximum(cube, 0.0)
        ee = exposure.mean(axis=0)
        pfe_95 = np.percentile(exposure, 95.0, axis=0)
        pfe_99 = np.percentile(exposure, 99.0, axis=0)
        span = grid[-1] - grid[0]
        epe = float(np.trapezoid(ee, grid) / span) if span > 0 else float(ee.mean())
        peak_idx = int(np.argmax(pfe_95))
        return ExposureProfile(
            time_grid=tuple(grid),
            ee=tuple(ee),
            epe=epe,
            pfe_95=tuple(pfe_95),
            pfe_99=tuple(pfe_99),
            peak_pfe=float(pfe_95[peak_idx]),
            peak_pfe_time=float(grid[peak_idx]),
        )
