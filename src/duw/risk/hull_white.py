"""Hull-White one-factor curve reconstruction for exposure simulation.

The short rate is ``r(t) = x(t) + alpha(t)`` with ``dx = -kappa x dt + sigma dW``
and ``alpha`` fitted so today's discount curve ``P0`` is reproduced exactly.
Given the simulated factor ``x(t)`` the whole discount curve at ``t`` is known
in closed form (Brigo & Mercurio, eq. 3.39):

    P(t, T) = P0(T) / P0(t) * exp(-B(t,T) x(t) + (V(t,T) - V(0,T) + V(0,t)) / 2)

with ``B(t,T) = (1 - exp(-kappa (T - t))) / kappa`` and ``V`` the variance of
the integrated short rate. This replaces the earlier "shift today's zero curve
in parallel" reconstruction, which neither rolled the curve forward nor carried
the convexity term, so the mean discounted MtM of a par swap drifted away from
zero.

**Measure.** Exposure is discounted deterministically, ``EE*(t) = P0(t) E[V+(t)]``,
which is exact when the expectation is taken under the ``t``-forward measure.
Under that measure ``x(t)`` is normal with variance
``sigma^2 (1 - exp(-2 kappa t)) / (2 kappa)`` (unchanged) and mean
``-M(t)``; :func:`forward_measure_drift` returns ``M(t)``. Shifting the
zero-mean simulated factor by ``-M(t)`` at each grid date makes
``P0(t) E[V(t)] = V(0)`` for any trade whose value is linear in zero-coupon
bonds, the martingale property the tests check.
"""

from __future__ import annotations

import math

import numpy as np

from duw.pricing.curves import DiscountCurve

_MIN_KAPPA = 1e-4


def _kappa(kappa: float) -> float:
    return max(float(kappa), _MIN_KAPPA)


def b_factor(t: float, maturity: float, kappa: float) -> float:
    """``B(t, T)``: sensitivity of ``ln P(t, T)`` to the factor ``x(t)``."""
    a = _kappa(kappa)
    return (1.0 - math.exp(-a * (maturity - t))) / a


def integrated_variance(t: float, maturity: float, kappa: float, sigma: float) -> float:
    """``V(t, T)``: variance of ``int_t^T x(u) du`` given ``x(t)``."""
    a = _kappa(kappa)
    d = maturity - t
    return (sigma * sigma / (a * a)) * (
        d
        + (2.0 / a) * math.exp(-a * d)
        - (1.0 / (2.0 * a)) * math.exp(-2.0 * a * d)
        - 3.0 / (2.0 * a)
    )


def forward_measure_drift(t: float, kappa: float, sigma: float) -> float:
    """``M(t)``: minus the mean of ``x(t)`` under the ``t``-forward measure."""
    a = _kappa(kappa)
    s2 = sigma * sigma
    return s2 / (a * a) * (1.0 - math.exp(-a * t)) - s2 / (2.0 * a * a) * (
        1.0 - math.exp(-2.0 * a * t)
    )


def forward_measure_drifts(grid, kappa: float, sigma: float) -> np.ndarray:
    """:func:`forward_measure_drift` on every grid time."""
    return np.array([forward_measure_drift(float(t), kappa, sigma) for t in grid])


class HullWhiteCurve(DiscountCurve):
    """The discount curve seen at simulation time ``t`` with factor ``x``.

    ``df(u)`` is scaled so that ``df(u) / df(t) = P(t, u)`` for ``u >= t``,
    which is how every pricer discounts from its valuation time. For ``u <= t``
    it returns today's ``P0(u)``; pricers never discount cashflows paid at or
    before their valuation time.
    """

    def __init__(
        self, base: DiscountCurve, t: float, x: float, kappa: float, sigma: float
    ) -> None:  # noqa: D107 - documented on the class
        self._base = base
        self._t_sim = float(t)
        self._x = float(x)
        self._kappa_v = _kappa(kappa)
        self._sigma = float(sigma)
        self._df_t = base.df(self._t_sim)
        self._v0t = integrated_variance(0.0, self._t_sim, kappa, sigma)
        # Attributes DiscountCurve helpers read.
        self._t = base._t
        self._log_df = base._log_df
        self._rate_front = base._rate_front
        self._rate_back = base._rate_back

    def df(self, t: float) -> float:
        """Discount factor from 0, consistent with ``P(t_sim, u)`` beyond ``t_sim``."""
        if t <= self._t_sim:
            return self._base.df(t)
        a, s = self._kappa_v, self._sigma
        b = b_factor(self._t_sim, t, a)
        convexity = 0.5 * (
            integrated_variance(self._t_sim, t, a, s)
            - integrated_variance(0.0, t, a, s)
            + self._v0t
        )
        return self._base.df(t) * math.exp(-b * self._x + convexity)
