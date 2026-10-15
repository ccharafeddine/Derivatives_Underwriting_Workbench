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

Repricing along a path: at node ``(path, t)`` the discount curve is the
Hull-White one-factor curve implied by the simulated factor
(:mod:`duw.risk.hull_white`, rolled forward and martingale-consistent under
each date's forward measure), the survival curve is today's bootstrapped curve
with its hazards scaled by the simulated credit multiplier, and the FX spot is
the simulated level. Each trade is then priced at
``valuation_time = t`` with the existing analytic pricers.

**Currency.** Each trade's mark-to-market is converted into one reporting
currency before the trades are summed. The reporting currency is the netting
set's shared trade currency, or the first trade's currency when the trades
disagree. An FX forward marks in its quote currency; every other product marks
in its trade currency. Conversion uses the simulated FX spot (the snapshot spot
at inception). If the snapshot has no pair linking a mark-to-market currency to
the reporting currency, :class:`MixedCurrencyError` is raised with a message
the UI can show directly — mixed-currency sets are never summed raw.

Pure numerics; no Qt.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from duw.domain.instruments import (
    CDS,
    IRS,
    CrossCurrencySwap,
    FXForward,
    NettingSet,
    Swaption,
    Trade,
)
from duw.domain.market import MarketSnapshot
from duw.domain.results import ExposureProfile
from duw.pricing.cds import price_cds
from duw.pricing.curves import DiscountCurve, SurvivalCurve, year_fraction
from duw.pricing.fx_forward import forward_rate_fx, price_fx_forward
from duw.pricing.irs import price_irs
from duw.pricing.swaption import price_swaption
from duw.pricing.xccy import price_cross_currency_swap
from duw.risk.hull_white import HullWhiteCurve, forward_measure_drifts


class MixedCurrencyError(ValueError):
    """Netting-set mark-to-market mixes currencies that cannot be converted.

    The message names the currencies and is safe to show to the user as-is.
    """


@dataclass(frozen=True)
class _CurveData:
    """Initial curve nodes for a currency, cached for fast shifted rebuilds."""

    tenors: tuple[float, ...]
    zero_rates: tuple[float, ...]


def mtm_currency(trade: Trade) -> str:
    """Currency the analytic pricer reports this trade's mark-to-market in.

    FX forwards mark in the quote currency. Every other product marks in
    ``trade.currency`` (a cross-currency swap already converts its foreign leg
    into the base currency inside the pricer).
    """
    if isinstance(trade, FXForward):
        return trade.quote_currency
    return trade.currency


def reporting_currency(netting_set: NettingSet | None) -> str:
    """Currency a netting set's aggregated mark-to-market is expressed in.

    The shared ``trade.currency`` when every trade agrees; otherwise the first
    trade's currency. Other mark-to-market amounts are converted into it.
    An empty set returns ``""``.
    """
    if netting_set is None or not netting_set.trades:
        return ""
    return netting_set.currencies[0]


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

        self._reporting_ccy = reporting_currency(netting_set)
        self._currencies = self._collect_currencies()
        self._issuers = self._collect_issuers()
        self._curve_data = {
            ccy: _CurveData(
                tenors=snapshot.curve(ccy).tenors,
                zero_rates=snapshot.curve(ccy).zero_rates,
            )
            for ccy in self._currencies
        }
        self._check_currency_conversions()
        self._fx_pairs = self._collect_fx_pairs()

    @property
    def reporting_currency(self) -> str:
        """Currency the net mark-to-market cube is expressed in."""
        return self._reporting_ccy

    @property
    def converted_currencies(self) -> tuple[str, ...]:
        """Mark-to-market currencies converted into the reporting currency."""
        report = self._reporting_ccy
        found = {
            mtm_currency(trade)
            for trade in self.netting_set.trades
            if mtm_currency(trade) != report
        }
        return tuple(sorted(found))

    # -- setup helpers ----------------------------------------------------- #
    def _collect_currencies(self) -> tuple[str, ...]:
        ccys: dict[str, None] = {}
        for trade in self.netting_set.trades:
            if isinstance(trade, FXForward):
                ccys.setdefault(trade.base_currency, None)
                ccys.setdefault(trade.quote_currency, None)
            elif isinstance(trade, CrossCurrencySwap):
                ccys.setdefault(trade.currency, None)
                ccys.setdefault(trade.foreign_currency, None)
            else:
                ccys.setdefault(trade.currency, None)
        return tuple(sorted(ccys))

    def _resolve_fx_pair(self, foreign: str, base: str) -> tuple[str, bool]:
        """Return ``(pair, invert)`` for base-per-foreign conversion.

        Picks whichever pair the snapshot carries; ``invert`` is True when the
        snapshot stores the reverse pair, so the caller reciprocates the spot.
        """
        direct, inverse = foreign + base, base + foreign
        if direct in self.snapshot.fx_spot:
            return direct, False
        if inverse in self.snapshot.fx_spot:
            return inverse, True
        raise KeyError(f"no FX pair linking {foreign} and {base} in the snapshot")

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
            elif isinstance(trade, CrossCurrencySwap):
                pair, _ = self._resolve_fx_pair(trade.foreign_currency, trade.currency)
                pairs.setdefault(pair, None)
        report = self._reporting_ccy
        for trade in self.netting_set.trades:
            ccy = mtm_currency(trade)
            if report and ccy != report:
                pair, _invert = self._resolve_fx_pair(ccy, report)
                pairs.setdefault(pair, None)
        return tuple(sorted(pairs))

    def _check_currency_conversions(self) -> None:
        """Reject mixed-currency sets the snapshot cannot convert."""
        report = self._reporting_ccy
        if not report:
            return
        missing: list[str] = []
        for trade in self.netting_set.trades:
            ccy = mtm_currency(trade)
            if ccy == report:
                continue
            try:
                self._resolve_fx_pair(ccy, report)
            except KeyError:
                missing.append(ccy)
        if not missing:
            return
        unique = tuple(sorted(set(missing)))
        examples = ", ".join(f"{ccy}{report} or {report}{ccy}" for ccy in unique)
        names = ", ".join(unique)
        raise MixedCurrencyError(
            f"Cannot net mark-to-market in {names} into {report}: the market "
            f"snapshot has no FX pair linking them. Add a spot ({examples}) "
            f"or keep the netting set in one currency."
        )

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
        trades: tuple[Trade, ...] | None = None,
    ) -> np.ndarray:
        """Return the net-MtM cube, shape ``(n_paths, len(time_grid))``.

        ``trades`` defaults to the whole netting set. Passing a subset reprices
        just those trades on the *same* simulated factor paths (the seed and the
        engine's factor set are unchanged), which is what makes an incremental
        exposure comparison consistent scenario-by-scenario.
        """
        from duw.risk.simulators import (
            simulate_credit_factor,
            simulate_fx_spot,
            simulate_rate_shift,
        )

        rng = np.random.default_rng(seed)
        grid = np.asarray(time_grid, dtype=float)

        # Hull-White factors per currency (drawn in a fixed order for
        # reproducibility), shifted to each date's t-forward measure so the
        # deterministic discounting used for EE / CVA is martingale-consistent.
        rate_paths: dict[str, np.ndarray] = {}
        for ccy in self._currencies:
            sigma = self._rate_sigma(ccy)
            x = simulate_rate_shift(
                rng, grid, sigma=sigma, n_paths=n_paths, kappa=self.kappa_rate
            )
            rate_paths[ccy] = x - forward_measure_drifts(grid, self.kappa_rate, sigma)

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

        # Reused across paths that share a shift (every path at t = 0, and any
        # later duplicate). Local to this call so two runs with the same seed
        # rebuild from scratch and stay bit-identical.
        curve_cache: dict[tuple[str, float, float], DiscountCurve] = {}
        survival_cache: dict[tuple[str, float], SurvivalCurve] = {}

        def curve_for(ccy: str, shift: float, t: float = 0.0) -> DiscountCurve:
            # float() so a numpy 0.0 and a Python 0.0 share one cached curve.
            key = (ccy, float(t), float(shift))
            found = curve_cache.get(key)
            if found is None:
                found = self._discount_curve(ccy, shift, t)
                curve_cache[key] = found
            return found

        def survival_for(issuer: str, log_factor: float) -> SurvivalCurve:
            key = (issuer, float(log_factor))
            found = survival_cache.get(key)
            if found is None:
                found = self._survival_for(issuer, log_factor)
                survival_cache[key] = found
            return found

        # FX spots per pair, with mean equal to the CIP forward at each node.
        fx_paths: dict[str, np.ndarray] = {}
        for pair in self._fx_pairs:
            base_ccy, quote_ccy = pair[:3], pair[3:]
            base0 = curve_for(base_ccy, 0.0)
            quote0 = curve_for(quote_ccy, 0.0)
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
                    ccy: curve_for(ccy, rate_paths[ccy][p, k], float(t))
                    for ccy in self._currencies
                }
                survivals = {
                    issuer: survival_for(issuer, credit_paths[issuer][p, k])
                    for issuer in self._issuers
                }
                spots = {pair: float(fx_paths[pair][p, k]) for pair in self._fx_pairs}
                cube[p, k] = self._net_mtm(float(t), curves, survivals, spots, trades)
        return cube

    def _rate_sigma(self, ccy: str) -> float:
        """Hull-White normal short-rate volatility for ``ccy``."""
        return float(self.snapshot.rate_vols.get(ccy, 0.01))

    def _base_curve(self, ccy: str) -> DiscountCurve:
        cache = self.__dict__.setdefault("_base_curve_cache", {})
        found = cache.get(ccy)
        if found is None:
            data = self._curve_data[ccy]
            found = DiscountCurve.from_zero_rates(data.tenors, data.zero_rates)
            cache[ccy] = found
        return found

    def _discount_curve(self, ccy: str, x: float, t: float = 0.0) -> DiscountCurve:
        """Curve for ``ccy`` seen at simulation time ``t`` with factor ``x``.

        At ``t = 0`` (with ``x = 0``) this is today's curve exactly. Later dates
        use the Hull-White reconstruction in :mod:`duw.risk.hull_white`.
        """
        base = self._base_curve(ccy)
        if t <= 0.0 and x == 0.0:
            return base
        return HullWhiteCurve(base, t, x, self.kappa_rate, self._rate_sigma(ccy))

    def _base_survival(self, issuer: str) -> SurvivalCurve:
        """Today's survival curve for ``issuer``, bootstrapped once per engine."""
        cache = self.__dict__.setdefault("_base_survival_cache", {})
        found = cache.get(issuer)
        if found is None:
            ccy = next(
                (
                    t.currency
                    for t in self.netting_set.trades
                    if isinstance(t, CDS) and t.reference_entity == issuer
                ),
                "USD",
            )
            found = SurvivalCurve.bootstrap(
                self.snapshot.credit(issuer),
                discount_curve=DiscountCurve.from_yield_curve(self.snapshot.curve(ccy)),
                as_of=self.as_of,
                currency=ccy,
            )
            cache[issuer] = found
        return found

    def _survival_for(self, issuer: str, log_factor: float) -> SurvivalCurve:
        """Today's curve with every forward hazard scaled by ``exp(log_factor)``."""
        return self._base_survival(issuer).scaled(float(np.exp(log_factor)))

    def _net_mtm(
        self,
        valuation_time: float,
        curves: dict[str, DiscountCurve],
        survivals: dict[str, SurvivalCurve],
        spots: dict[str, float],
        trades: tuple[Trade, ...] | None = None,
    ) -> float:
        trade_list = self.netting_set.trades if trades is None else trades
        report = self._reporting_ccy
        total = 0.0
        for trade in trade_list:
            mtm = self._price(trade, valuation_time, curves, survivals, spots)
            ccy = mtm_currency(trade)
            if report and ccy != report:
                mtm = self._to_reporting(mtm, ccy, spots)
            total += mtm
        return total

    def _to_reporting(self, amount: float, ccy: str, spots: dict[str, float]) -> float:
        """Convert ``amount`` from ``ccy`` into the reporting currency.

        ``spots`` are the path's simulated FX levels, keyed by the snapshot's
        pair name. At inception those levels equal the snapshot spot.
        """
        report = self._reporting_ccy
        pair, invert = self._resolve_fx_pair(ccy, report)
        try:
            spot = spots[pair]
        except KeyError as exc:
            raise MixedCurrencyError(
                f"No FX spot for {pair} to convert {ccy} into {report}."
            ) from exc
        if not np.isfinite(spot) or spot <= 0.0:
            raise MixedCurrencyError(
                f"FX spot for {pair} is {spot}, so {ccy} cannot be converted "
                f"into {report}."
            )
        per_unit = (1.0 / spot) if invert else spot
        return amount * per_unit

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
        if isinstance(trade, Swaption):
            return price_swaption(
                trade, curves[trade.currency], self.as_of, valuation_time
            )
        if isinstance(trade, CrossCurrencySwap):
            pair, invert = self._resolve_fx_pair(trade.foreign_currency, trade.currency)
            spot = spots[pair]
            base_per_foreign = (1.0 / spot) if invert else spot
            return price_cross_currency_swap(
                trade,
                curves[trade.currency],
                curves[trade.foreign_currency],
                base_per_foreign,
                self.as_of,
                valuation_time,
            )
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

    def inception_mtms(self) -> list[tuple[Trade, float]]:
        """Each trade's mark-to-market today, in the reporting currency.

        Prices on today's curves, survival curves and FX spots (the same inputs
        every path shares at t = 0), for per-trade tables such as the deal
        overview's netting-set breakdown.
        """
        curves = {ccy: self._base_curve(ccy) for ccy in self._currencies}
        survivals = {iss: self._base_survival(iss) for iss in self._issuers}
        spots = dict(self.snapshot.fx_spot)
        out: list[tuple[Trade, float]] = []
        for trade in self.netting_set.trades:
            mtm = self._net_mtm(0.0, curves, survivals, spots, trades=(trade,))
            out.append((trade, mtm))
        return out

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
