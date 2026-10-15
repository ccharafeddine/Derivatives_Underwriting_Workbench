"""Discount and survival curves plus scheduling helpers.

Pure numerics (numpy only, no Qt). Two curve objects back all pricing:

- :class:`DiscountCurve` — discount factors by time, interpolated log-linearly
  on the discount factor (equivalently, linearly on ``ln DF``) with flat
  zero-rate extrapolation beyond the node range. This guarantees ``df(0) == 1``
  and, for positive zero rates, discount factors that are strictly decreasing in
  tenor. Forward discount factors and simple forward rates come off the same
  object so a floating leg can be projected in a single-curve framework.
- :class:`SurvivalCurve` — issuer survival probabilities from a piecewise-
  constant forward-hazard bootstrap that reprices the quoted CDS spreads.

Time is always a **year fraction from the market as-of date**. A valuation at a
future time ``t_v`` discounts a later cashflow at ``u`` by
``df(u) / df(t_v)``; this is what lets a pricer be called both at inception
(``t_v = 0``) and along a simulated path.

Unit conventions: zero rates and hazards are continuously-compounded decimals;
CDS spreads are decimals; recovery is a decimal in ``[0, 1)``.
"""

from __future__ import annotations

from datetime import date

import numpy as np

from duw.domain.market import CreditCurve, YieldCurve

# Schedule anchor for a bootstrap called without a market as-of date.
_NEUTRAL_AS_OF = date(2000, 1, 3)


def year_fraction(as_of: date, d: date) -> float:
    """Year fraction from ``as_of`` to ``d`` on an ACT/365.25 basis."""
    return (d - as_of).days / 365.25


def period_schedule(
    start_t: float, end_t: float, per_year: int
) -> list[tuple[float, float]]:
    """Return equal-length accrual periods over ``[start_t, end_t]``.

    Each entry is ``(accrual_start, accrual_end)`` as year fractions from the
    as-of date; the period payment is made at ``accrual_end``. Periods are
    equal-length (day-count conventions are approximated by this year-fraction
    accrual in v1). Always returns at least one period.
    """
    span = end_t - start_t
    n = max(1, round(span * per_year))
    dt = span / n
    return [(start_t + k * dt, start_t + (k + 1) * dt) for k in range(n)]


class DiscountCurve:
    """Discount factors interpolated log-linearly with flat-rate extrapolation."""

    def __init__(
        self, tenors: tuple[float, ...], discount_factors: tuple[float, ...]
    ) -> None:
        if len(tenors) != len(discount_factors):
            raise ValueError("tenors and discount_factors length mismatch")
        if not tenors:
            raise ValueError("discount curve needs at least one node")
        t = np.asarray(tenors, dtype=float)
        dfs = np.asarray(discount_factors, dtype=float)
        order = np.argsort(t)
        self._t = t[order]
        self._log_df = np.log(dfs[order])
        if self._t[0] <= 0.0:
            raise ValueError("node tenors must be strictly positive")
        # Flat zero rates implied by the first and last nodes, used to
        # extrapolate below the first and above the last tenor.
        self._rate_front = -self._log_df[0] / self._t[0]
        self._rate_back = -self._log_df[-1] / self._t[-1]

    @classmethod
    def from_zero_rates(
        cls, tenors: tuple[float, ...], zero_rates: tuple[float, ...]
    ) -> DiscountCurve:
        """Build from continuously-compounded zero rates: ``DF = exp(-r t)``."""
        t = np.asarray(tenors, dtype=float)
        r = np.asarray(zero_rates, dtype=float)
        return cls(tuple(t), tuple(np.exp(-r * t)))

    @classmethod
    def from_yield_curve(cls, curve: YieldCurve) -> DiscountCurve:
        """Build from a :class:`~duw.domain.market.YieldCurve` snapshot."""
        return cls.from_zero_rates(curve.tenors, curve.zero_rates)

    def df(self, t: float) -> float:
        """Discount factor from time 0 to ``t`` (``df(0) == 1``)."""
        if t <= 0.0:
            return 1.0
        if t <= self._t[0]:
            return float(np.exp(-self._rate_front * t))
        if t >= self._t[-1]:
            return float(np.exp(-self._rate_back * t))
        # Linear interpolation of ln(DF) in t (log-linear on the DF).
        log_df = float(np.interp(t, self._t, self._log_df))
        return float(np.exp(log_df))

    def zero_rate(self, t: float) -> float:
        """Continuously-compounded zero rate to ``t``."""
        if t <= 0.0:
            return self._rate_front
        return -np.log(self.df(t)) / t

    def forward_df(self, t1: float, t2: float) -> float:
        """Discount factor from ``t1`` to ``t2`` (``t2 >= t1``)."""
        return self.df(t2) / self.df(t1)

    def forward_simple_rate(self, t1: float, t2: float) -> float:
        """Simple (linear) forward rate over ``[t1, t2]``."""
        if t2 <= t1:
            raise ValueError("t2 must exceed t1 for a forward rate")
        return (self.df(t1) / self.df(t2) - 1.0) / (t2 - t1)


class SurvivalCurve:
    """Issuer survival probabilities with piecewise-constant forward hazards.

    :meth:`bootstrap` solves the hazards node by node so that a standard CDS
    (quarterly premium, ACT/360 accrual, accrual-on-default, protection leg
    integrated against the discount curve) to each quoted tenor prices at par
    on its quoted spread, the same construction as QuantLib's
    ``PiecewiseFlatHazardRate`` with ``SpreadCdsHelper``. Forward hazards are
    floored at zero, so survival is monotone non-increasing.
    """

    def __init__(
        self, node_tenors: tuple[float, ...], cumulative_hazard: tuple[float, ...]
    ) -> None:
        t = np.asarray(node_tenors, dtype=float)
        h = np.asarray(cumulative_hazard, dtype=float)
        order = np.argsort(t)
        self._t = t[order]
        self._cum_hazard = h[order]
        # Forward hazard on the segment ending at the last node, for extrapolation.
        if len(self._t) == 1:
            self._lambda_back = self._cum_hazard[-1] / self._t[-1]
        else:
            dt = self._t[-1] - self._t[-2]
            self._lambda_back = (self._cum_hazard[-1] - self._cum_hazard[-2]) / dt

    @classmethod
    def from_flat_hazard(
        cls, hazard: float, tenors: tuple[float, ...] = (1.0, 5.0, 10.0)
    ) -> SurvivalCurve:
        """Constant forward hazard ``hazard`` at every horizon."""
        return cls(tuple(tenors), tuple(hazard * t for t in tenors))

    @classmethod
    def bootstrap(
        cls,
        credit_curve: CreditCurve,
        recovery: float | None = None,
        *,
        discount_curve: DiscountCurve | None = None,
        as_of: date | None = None,
        currency: str = "USD",
    ) -> SurvivalCurve:
        """Bootstrap a survival curve that reprices every quoted CDS spread.

        ``discount_curve`` should be the curve of the CDS currency; without one
        the legs are left undiscounted (a zero-rate curve), which is only a
        fallback for callers with no rates context. ``as_of`` anchors the dated
        premium schedules; it defaults to a fixed neutral Monday.
        """
        from duw.pricing.cds import bootstrap_cumulative_hazard

        nodes, cum = bootstrap_cumulative_hazard(
            credit_curve,
            discount_curve or DiscountCurve.from_zero_rates((1.0,), (0.0,)),
            as_of or _NEUTRAL_AS_OF,
            recovery=recovery,
            currency=currency,
        )
        return cls(nodes, cum)

    def scaled(self, multiplier: float) -> SurvivalCurve:
        """Same shape with every forward hazard multiplied by ``multiplier``."""
        out = SurvivalCurve.__new__(SurvivalCurve)
        out._t = self._t
        out._cum_hazard = self._cum_hazard * multiplier
        out._lambda_back = self._lambda_back * multiplier
        return out

    def _cumulative_hazard(self, t: float) -> float:
        if t <= 0.0:
            return 0.0
        if t <= self._t[0]:
            # Flat hazard from 0 to the first node.
            return self._cum_hazard[0] * (t / self._t[0])
        if t >= self._t[-1]:
            return float(self._cum_hazard[-1] + self._lambda_back * (t - self._t[-1]))
        return float(np.interp(t, self._t, self._cum_hazard))

    def survival(self, t: float) -> float:
        """Survival probability to ``t`` (``survival(0) == 1``)."""
        return float(np.exp(-self._cumulative_hazard(t)))

    def default_prob(self, t: float) -> float:
        """Cumulative default probability to ``t``."""
        return 1.0 - self.survival(t)

    def hazard(self, t: float) -> float:
        """Piecewise-constant forward hazard at ``t``."""
        if t >= self._t[-1]:
            return float(self._lambda_back)
        if t <= self._t[0]:
            return float(self._cum_hazard[0] / self._t[0])
        i = int(np.searchsorted(self._t, t, side="right"))
        dt = self._t[i] - self._t[i - 1]
        return float((self._cum_hazard[i] - self._cum_hazard[i - 1]) / dt)

    def marginal_default_prob(self, t1: float, t2: float) -> float:
        """Unconditional default probability in ``(t1, t2]``."""
        return self.survival(t1) - self.survival(t2)

    def conditional_survival(self, t: float, from_t: float) -> float:
        """Survival to ``t`` conditional on being alive at ``from_t``."""
        s0 = self.survival(from_t)
        if s0 <= 0.0:
            return 0.0
        return self.survival(t) / s0
