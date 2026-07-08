"""Collateral (CSA) modeling.

Applies a Credit Support Annex to the net-MtM cube with a simplified margin-
period-of-risk (MPoR) model and reports collateralized exposure alongside the
uncollateralized profile so the risk mitigation is explicit.

CSA parameters:

- **threshold** — unsecured amount below which no collateral is called.
- **MTA** — minimum transfer amount; collateral only moves when the required
  amount clears it.
- **initial margin (IM)** — collateral held up front, independent of MtM.
- **MPoR** — the gap (in business days) over which collateral cannot be
  re-called, so exposure can drift before fresh margin arrives.

Model (path-wise, per node ``(path, t)``):

    E          = max(net MtM, 0)                         # uncollateralized
    VM         = max(value one MPoR ago - threshold, 0)  # variation margin held
    VM         = VM if VM >= MTA else 0                  # MTA gate
    E_collat   = max(E - VM - IM, 0)

The one-MPoR lag (``delta = mpor_days / 252``) is what leaves residual gap risk:
collateral reflects the exposure as of ``t - delta``, so a move over the MPoR is
uncollateralized. With no CSA (very large threshold, zero IM) the collateralized
exposure recovers the uncollateralized profile.

**Multi-currency collateral:** when collateral is posted in a currency other than
the netting-set currency, its value drifts with FX over the MPoR. This is modelled
with a supervisory-style ``fx_haircut`` applied to the posted collateral value
(variation and initial margin), so posting in a different currency mitigates less
than same-currency collateral. A ``0`` haircut recovers single-currency behavior.

Pure numerics; no Qt.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from duw.domain.results import CollateralResult

# Business days per year, used to convert the MPoR from days to a year fraction.
BUSINESS_DAYS_PER_YEAR = 252.0


@dataclass(frozen=True)
class CSA:
    """Credit Support Annex parameters (amounts in the netting-set currency).

    ``collateral_currency`` is informational; ``fx_haircut`` (a decimal, e.g.
    ``0.08``) discounts posted collateral value when it is in a different currency
    than the exposure. ``0`` is same-currency collateral.
    """

    threshold: float = 0.0
    mta: float = 0.0
    initial_margin: float = 0.0
    mpor_days: int = 10
    collateral_currency: str = ""
    fx_haircut: float = 0.0


def _lagged_values(
    cube: np.ndarray, time_grid: tuple[float, ...], delta: float
) -> np.ndarray:
    """Return the netting-set value at ``t_k - delta`` for every node.

    Linear interpolation along the time axis; queries at or before ``t_0`` take
    the initial value (all paths share the deterministic ``t_0`` column).
    """
    grid = np.asarray(time_grid, dtype=float)
    lag = np.empty_like(cube)
    for k, t in enumerate(grid):
        tl = t - delta
        if tl <= grid[0]:
            lag[:, k] = cube[:, 0]
            continue
        j = int(np.searchsorted(grid, tl, side="right")) - 1
        j = min(max(j, 0), len(grid) - 2)
        span = grid[j + 1] - grid[j]
        w = 0.0 if span <= 0 else (tl - grid[j]) / span
        lag[:, k] = (1.0 - w) * cube[:, j] + w * cube[:, j + 1]
    return lag


def apply_csa(cube: np.ndarray, time_grid: tuple[float, ...], csa: CSA) -> np.ndarray:
    """Return the collateralized exposure cube (non-negative) under ``csa``."""
    delta = csa.mpor_days / BUSINESS_DAYS_PER_YEAR
    exposure = np.maximum(cube, 0.0)
    lagged = _lagged_values(cube, time_grid, delta)
    variation_margin = np.maximum(lagged - csa.threshold, 0.0)
    # Minimum transfer amount: no collateral moves below the MTA.
    variation_margin = np.where(variation_margin >= csa.mta, variation_margin, 0.0)
    # FX haircut discounts the value of collateral posted in another currency.
    effective = (1.0 - csa.fx_haircut) * (variation_margin + csa.initial_margin)
    return np.maximum(exposure - effective, 0.0)


def _peak_pfe(exposure: np.ndarray, quantile: float = 95.0) -> float:
    """Peak over time of the exposure quantile across paths."""
    return float(np.percentile(exposure, quantile, axis=0).max())


def compute_collateral(
    cube: np.ndarray, time_grid: tuple[float, ...], csa: CSA
) -> CollateralResult:
    """Uncollateralized vs collateralized EE and peak PFE under ``csa``."""
    uncollat = np.maximum(cube, 0.0)
    collat = apply_csa(cube, time_grid, csa)
    return CollateralResult(
        threshold=csa.threshold,
        mta=csa.mta,
        initial_margin=csa.initial_margin,
        mpor_days=csa.mpor_days,
        collateral_currency=csa.collateral_currency,
        fx_haircut=csa.fx_haircut,
        time_grid=tuple(float(t) for t in time_grid),
        ee_uncollateralized=tuple(uncollat.mean(axis=0)),
        ee_collateralized=tuple(collat.mean(axis=0)),
        peak_pfe_uncollateralized=_peak_pfe(uncollat),
        peak_pfe_collateralized=_peak_pfe(collat),
    )
