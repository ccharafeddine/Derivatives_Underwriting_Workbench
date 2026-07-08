"""CVA / DVA / FVA and wrong-way risk.

Prices the counterparty's default risk from the exposure profile, the survival
curve, and discounting. Unilateral CVA (a cost to us) is

    CVA = LGD * sum_i DF(t_i) * EE(t_i) * mPD_i

where ``mPD_i = S(t_{i-1}) - S(t_i)`` is the counterparty's unconditional
default probability over interval ``i`` from its survival curve, and ``EE`` is
expected (positive) exposure. DVA (a benefit to us, from our own possible
default) is the symmetric leg on expected negative exposure ``ENE`` with our own
survival curve and LGD. The bilateral net is ``BCVA = CVA - DVA``. FVA is the
funding valuation adjustment on the net uncollateralized exposure.

**Wrong-way risk** — exposure tending to rise as the counterparty's credit
deteriorates — is captured by :func:`wrong_way_adjusted_ee`, which reweights the
per-date exposure toward its higher paths by a correlation ``rho`` in
``[-1, 1]``. ``rho = 0`` reproduces the mean EE (independence); ``rho > 0``
raises CVA (wrong-way), ``rho < 0`` lowers it (right-way). This is a simplified
one-factor rank tilt, not a full copula bootstrap — noted honestly.

Pure numerics; no Qt.
"""

from __future__ import annotations

import numpy as np

from duw.domain.market import CreditCurve
from duw.domain.results import CVAResult
from duw.pricing.curves import DiscountCurve, SurvivalCurve

# Standard tenors (years) for building a flat own-credit survival curve.
_OWN_CURVE_TENORS: tuple[float, ...] = (0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0)


def expected_exposures_from_cube(cube: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(EE, ENE)`` per time column from a net-MtM cube.

    ``EE`` is the mean positive exposure to us; ``ENE`` is the mean of the
    negative part expressed as a positive number (the counterparty's exposure
    to us), used for DVA.
    """
    ee = np.maximum(cube, 0.0).mean(axis=0)
    ene = np.maximum(-cube, 0.0).mean(axis=0)
    return ee, ene


def wrong_way_adjusted_ee(cube: np.ndarray, rho: float) -> np.ndarray:
    """Expected exposure per date, tilted for wrong-way risk by ``rho``.

    Each path's exposure at a date is weighted by ``1 + rho * (2*rank - 1)``
    where ``rank`` is its exposure percentile in ``[0, 1]``; the weighted mean is
    returned. ``rho = 0`` gives the plain mean EE (independence). Weights are
    floored at 0, so ``|rho| <= 1`` keeps them non-negative.
    """
    exposure = np.maximum(cube, 0.0)
    if rho == 0.0:
        return exposure.mean(axis=0)
    n_paths = exposure.shape[0]
    ee = np.empty(exposure.shape[1])
    for t in range(exposure.shape[1]):
        col = exposure[:, t]
        ranks = (np.argsort(np.argsort(col)) + 0.5) / n_paths  # percentile in [0,1]
        weights = np.maximum(1.0 + rho * (2.0 * ranks - 1.0), 0.0)
        total = weights.sum()
        ee[t] = float((weights * col).sum() / total) if total > 0 else float(col.mean())
    return ee


def compute_fva(
    time_grid: tuple[float, ...],
    ee: np.ndarray | tuple[float, ...],
    ene: np.ndarray | tuple[float, ...],
    discount_curve: DiscountCurve,
    funding_spread: float,
) -> float:
    """Funding valuation adjustment on the net uncollateralized exposure.

    Simplified symmetric FVA:
    ``FVA = s_F * sum_i DF(t_i) * (EE - ENE)_avg * dt_i`` — the funding cost of
    positive exposure net of the benefit of negative exposure. ``0`` when the
    funding spread is ``0``.
    """
    grid = np.asarray(time_grid, dtype=float)
    ee_a = np.asarray(ee, dtype=float)
    ene_a = np.asarray(ene, dtype=float)
    fva = 0.0
    for i in range(1, len(grid)):
        dt = grid[i] - grid[i - 1]
        df = discount_curve.df(float(grid[i]))
        net_now = ee_a[i] - ene_a[i]
        net_prev = ee_a[i - 1] - ene_a[i - 1]
        fva += funding_spread * df * 0.5 * (net_now + net_prev) * dt
    return float(fva)


def constant_hazard_survival(
    spread: float,
    recovery: float = 0.4,
    tenors: tuple[float, ...] = _OWN_CURVE_TENORS,
) -> SurvivalCurve:
    """Build a flat-spread survival curve (e.g. for our own credit / DVA)."""
    flat = CreditCurve(
        issuer="OWN",
        tenors=tenors,
        spreads=tuple(spread for _ in tenors),
        recovery_rate=recovery,
    )
    return SurvivalCurve.bootstrap(flat)


def _adjustment_leg(
    time_grid: tuple[float, ...],
    exposures: np.ndarray | tuple[float, ...],
    discount_curve: DiscountCurve,
    survival: SurvivalCurve,
    lgd: float,
) -> tuple[float, np.ndarray]:
    """Discounted expected-loss leg: LGD * sum DF * exposure * marginal PD.

    Returns the total and the per-interval contributions aligned to
    ``time_grid`` (index 0 is 0 since the first interval starts at ``t_0``).
    """
    grid = np.asarray(time_grid, dtype=float)
    exp = np.asarray(exposures, dtype=float)
    contrib = np.zeros(len(grid))
    s_prev = survival.survival(float(grid[0]))
    for i in range(1, len(grid)):
        s_curr = survival.survival(float(grid[i]))
        marginal_pd = s_prev - s_curr
        df = discount_curve.df(float(grid[i]))
        contrib[i] = lgd * df * float(exp[i]) * marginal_pd
        s_prev = s_curr
    return float(contrib.sum()), contrib


def compute_cva(
    time_grid: tuple[float, ...],
    ee: np.ndarray | tuple[float, ...],
    discount_curve: DiscountCurve,
    survival: SurvivalCurve,
    lgd: float,
) -> tuple[float, np.ndarray]:
    """Unilateral CVA and its per-interval contributions."""
    return _adjustment_leg(time_grid, ee, discount_curve, survival, lgd)


def compute_dva(
    time_grid: tuple[float, ...],
    ene: np.ndarray | tuple[float, ...],
    discount_curve: DiscountCurve,
    own_survival: SurvivalCurve,
    own_lgd: float,
) -> tuple[float, np.ndarray]:
    """Unilateral DVA (own credit) and its per-interval contributions."""
    return _adjustment_leg(time_grid, ene, discount_curve, own_survival, own_lgd)


def compute_bcva(
    time_grid: tuple[float, ...],
    ee: np.ndarray | tuple[float, ...],
    ene: np.ndarray | tuple[float, ...],
    discount_curve: DiscountCurve,
    cp_survival: SurvivalCurve,
    cp_lgd: float,
    own_survival: SurvivalCurve | None = None,
    own_lgd: float = 0.0,
    funding_spread: float = 0.0,
    wwr_correlation: float = 0.0,
) -> CVAResult:
    """Bilateral CVA plus FVA as a :class:`CVAResult`.

    DVA is zero unless both an ``own_survival`` curve and a positive ``own_lgd``
    are supplied. ``funding_spread`` drives FVA (0 => no FVA). ``ee`` is the
    already-wrong-way-adjusted expected exposure; ``wwr_correlation`` is recorded
    for reporting.
    """
    cva, cva_contrib = compute_cva(time_grid, ee, discount_curve, cp_survival, cp_lgd)
    if own_survival is not None and own_lgd > 0.0:
        dva, _ = compute_dva(time_grid, ene, discount_curve, own_survival, own_lgd)
    else:
        dva = 0.0
    fva = compute_fva(time_grid, ee, ene, discount_curve, funding_spread)
    return CVAResult(
        cva=cva,
        dva=dva,
        bcva=cva - dva,
        fva=fva,
        lgd=cp_lgd,
        wwr_correlation=wwr_correlation,
        time_grid=tuple(float(t) for t in time_grid),
        contributions=tuple(float(c) for c in cva_contrib),
    )
