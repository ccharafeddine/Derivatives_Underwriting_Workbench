"""CVA / DVA / BCVA.

Prices the counterparty's default risk from the exposure profile, the survival
curve, and discounting. Unilateral CVA (a cost to us) is

    CVA = LGD * sum_i DF(t_i) * EE(t_i) * mPD_i

where ``mPD_i = S(t_{i-1}) - S(t_i)`` is the counterparty's unconditional
default probability over interval ``i`` from its survival curve, and ``EE`` is
expected (positive) exposure. DVA (a benefit to us, from our own possible
default) is the symmetric leg on expected negative exposure ``ENE`` with our own
survival curve and LGD. The bilateral net is ``BCVA = CVA - DVA``.

All three are computed under the standard v1 assumption that exposure and the
counterparty's default are independent. Wrong-way risk (correlation between the
two) is a deliberate v2 extension; :func:`apply_wrong_way_risk` marks the hook
but is not implemented.

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
) -> CVAResult:
    """Bilateral CVA: CVA, DVA, and ``BCVA = CVA - DVA`` as a :class:`CVAResult`.

    DVA is zero unless both an ``own_survival`` curve and a positive ``own_lgd``
    are supplied.
    """
    cva, cva_contrib = compute_cva(time_grid, ee, discount_curve, cp_survival, cp_lgd)
    if own_survival is not None and own_lgd > 0.0:
        dva, _ = compute_dva(time_grid, ene, discount_curve, own_survival, own_lgd)
    else:
        dva = 0.0
    return CVAResult(
        cva=cva,
        dva=dva,
        bcva=cva - dva,
        lgd=cp_lgd,
        time_grid=tuple(float(t) for t in time_grid),
        contributions=tuple(float(c) for c in cva_contrib),
    )


def apply_wrong_way_risk(*_args: object, **_kwargs: object) -> None:
    """Hook (v2): scale marginal PDs by exposure-credit correlation.

    Wrong-way risk — the tendency of exposure to rise as the counterparty's
    credit deteriorates — is out of scope for v1, where CVA is computed under
    independence. This function marks the extension point; a v2 implementation
    would introduce a correlation between the simulated credit factor and the
    exposure paths and reweight the marginal default probabilities accordingly.
    """
    raise NotImplementedError("wrong-way risk is a v2 extension point")
