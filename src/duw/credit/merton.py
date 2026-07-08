"""Merton / KMV-style distance-to-default.

Treats the firm's equity as a European call on its assets struck at the debt
(default point). Given observable equity value ``E``, equity volatility
``sigma_E``, debt ``D``, and a risk-free rate ``r`` over horizon ``T``, we solve
the two structural equations

    E          = V * N(d1) - D * exp(-r T) * N(d2)
    sigma_E E  = sigma_V * V * N(d1)

for the latent asset value ``V`` and asset volatility ``sigma_V``, where

    d1 = (ln(V/D) + (r + 0.5 sigma_V^2) T) / (sigma_V sqrt(T))
    d2 = d1 - sigma_V sqrt(T).

Distance-to-default uses the asset drift ``mu`` (defaulting to ``r``):

    DtD = (ln(V/D) + (mu - 0.5 sigma_V^2) T) / (sigma_V sqrt(T)),   PD = N(-DtD).

The solve is done with :func:`scipy.optimize.fsolve` from a sensible starting
guess and validated; if it fails to converge or the inputs are degenerate we
fall back to the standard approximation ``V = E + D e^{-rT}``,
``sigma_V = sigma_E E / V`` so the model always returns a usable result.

Pure numerics; no Qt.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, log, sqrt

import numpy as np
from scipy.optimize import fsolve
from scipy.stats import norm

from duw.domain.counterparty import Financials


@dataclass(frozen=True)
class MertonResult:
    """Outputs of the Merton solve."""

    asset_value: float
    asset_volatility: float
    distance_to_default: float
    pd: float
    converged: bool


def _distance_to_default(
    asset_value: float,
    debt: float,
    asset_vol: float,
    horizon: float,
    drift: float,
) -> float:
    return (log(asset_value / debt) + (drift - 0.5 * asset_vol**2) * horizon) / (
        asset_vol * sqrt(horizon)
    )


def solve_merton(
    equity_value: float,
    equity_vol: float,
    debt: float,
    risk_free_rate: float,
    horizon: float = 1.0,
    asset_drift: float | None = None,
) -> MertonResult:
    """Solve the Merton system and return asset value/vol, DtD, and PD."""
    drift = risk_free_rate if asset_drift is None else asset_drift

    # Degenerate inputs: no equity cushion or no debt -> use direct fallbacks.
    if equity_value <= 0.0 or equity_vol <= 0.0 or debt <= 0.0:
        return _fallback(equity_value, equity_vol, debt, horizon, drift)

    disc_debt = debt * exp(-risk_free_rate * horizon)
    v0 = equity_value + disc_debt
    s0 = equity_vol * equity_value / v0
    sqrt_t = sqrt(horizon)

    def residuals(x: np.ndarray) -> list[float]:
        v, sigma_v = x
        if v <= 0.0 or sigma_v <= 0.0:
            return [1e6, 1e6]
        d1 = (log(v / debt) + (risk_free_rate + 0.5 * sigma_v**2) * horizon) / (
            sigma_v * sqrt_t
        )
        d2 = d1 - sigma_v * sqrt_t
        eq1 = v * norm.cdf(d1) - debt * exp(-risk_free_rate * horizon) * norm.cdf(d2)
        eq2 = sigma_v * v * norm.cdf(d1) - equity_vol * equity_value
        return [eq1 - equity_value, eq2]

    solution, _info, flag, _msg = fsolve(
        residuals, x0=[v0, s0], full_output=True, xtol=1e-10
    )
    v, sigma_v = float(solution[0]), float(solution[1])
    converged = flag == 1 and v > 0.0 and sigma_v > 0.0
    if not converged:
        return _fallback(equity_value, equity_vol, debt, horizon, drift)

    dtd = _distance_to_default(v, debt, sigma_v, horizon, drift)
    return MertonResult(
        asset_value=v,
        asset_volatility=sigma_v,
        distance_to_default=dtd,
        pd=float(norm.cdf(-dtd)),
        converged=True,
    )


def _fallback(
    equity_value: float,
    equity_vol: float,
    debt: float,
    horizon: float,
    drift: float,
) -> MertonResult:
    """Closed-form approximation used when the solve cannot be trusted."""
    v = max(equity_value, 0.0) + max(debt, 0.0)
    # Wiped-out equity (or no debt/assets) means the firm sits at or past its
    # default boundary and the structural model is not meaningful; treat as
    # certain default rather than returning a misleadingly low PD.
    if v <= 0.0 or debt <= 0.0 or equity_value <= 0.0:
        return MertonResult(
            asset_value=max(v, 0.0),
            asset_volatility=max(equity_vol, 1e-6),
            distance_to_default=float("-inf"),
            pd=1.0,
            converged=False,
        )
    sigma_v = max(equity_vol * max(equity_value, 0.0) / v, 1e-6)
    dtd = _distance_to_default(v, debt, sigma_v, horizon, drift)
    return MertonResult(
        asset_value=v,
        asset_volatility=sigma_v,
        distance_to_default=dtd,
        pd=float(norm.cdf(-dtd)),
        converged=False,
    )


def merton_from_financials(
    financials: Financials,
    risk_free_rate: float,
    horizon: float = 1.0,
    asset_drift: float | None = None,
) -> MertonResult:
    """Run the Merton solve using a counterparty's financials.

    Debt (the default point) is taken as total liabilities.
    """
    return solve_merton(
        equity_value=financials.market_equity,
        equity_vol=financials.equity_volatility,
        debt=financials.total_liabilities,
        risk_free_rate=risk_free_rate,
        horizon=horizon,
        asset_drift=asset_drift,
    )
