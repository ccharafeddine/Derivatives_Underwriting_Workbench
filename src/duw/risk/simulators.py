"""Seeded risk-factor simulators.

Three factors drive exposure, each simulated on an explicit time grid with an
explicit :class:`numpy.random.Generator` (no global random state, so a fixed
seed reproduces every path):

- **Rates** — a mean-reverting parallel shift of the zero curve, ``Delta(t)``,
  starting at ``Delta(0) = 0``. The projected discount curve at a future node is
  the initial curve with every zero rate shifted by ``Delta``. This is the
  Vasicek / shocked-curve approximation that CLAUDE.md permits as a v1 fallback
  in place of a fully calibrated Hull-White one-factor bond reconstruction; it
  anchors the ``t = 0`` node to the true inception curve and keeps the factor
  stationary. Documented here rather than pretending to be full HW1F.
- **FX** — geometric Brownian motion for the spot with drift chosen so the mean
  simulated spot equals the covered-interest-parity forward at each horizon.
- **Credit** — a mean-reverting factor in log space; the CDS spread multiplier
  is ``exp(Y(t))``, which stays positive and reverts toward the initial curve.

All processes return arrays shaped ``(n_paths, n_times)`` aligned to ``grid``.
Pure numerics; no Qt.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def _grid_steps(grid: Sequence[float]) -> np.ndarray:
    """Return step sizes from time 0 through each grid point.

    The first step runs from 0 to ``grid[0]`` (which may itself be 0, giving a
    zero-length first step so the initial column equals the start state).
    """
    times = np.asarray(grid, dtype=float)
    prev = np.concatenate(([0.0], times[:-1]))
    return times - prev


def simulate_ou(
    rng: np.random.Generator,
    grid: Sequence[float],
    kappa: float,
    sigma: float,
    n_paths: int,
    x0: float = 0.0,
    theta: float = 0.0,
) -> np.ndarray:
    """Simulate an Ornstein-Uhlenbeck (Vasicek) process on ``grid``.

    Uses the exact transition ``x_{k} = x_{k-1} e^{-kappa dt} +
    theta (1 - e^{-kappa dt}) + std * Z`` with
    ``std = sigma sqrt((1 - e^{-2 kappa dt}) / (2 kappa))``, valid for any step
    size. Returns an ``(n_paths, n_times)`` array. ``kappa <= 0`` falls back to a
    driftless Brownian scaling.
    """
    steps = _grid_steps(grid)
    out = np.empty((n_paths, len(steps)), dtype=float)
    x = np.full(n_paths, float(x0))
    for k, dt in enumerate(steps):
        if dt <= 0.0:
            out[:, k] = x
            continue
        if kappa > 0.0:
            decay = np.exp(-kappa * dt)
            std = sigma * np.sqrt((1.0 - np.exp(-2.0 * kappa * dt)) / (2.0 * kappa))
            x = x * decay + theta * (1.0 - decay) + std * rng.standard_normal(n_paths)
        else:
            x = x + sigma * np.sqrt(dt) * rng.standard_normal(n_paths)
        out[:, k] = x
    return out


def simulate_rate_shift(
    rng: np.random.Generator,
    grid: Sequence[float],
    sigma: float,
    n_paths: int,
    kappa: float = 0.10,
) -> np.ndarray:
    """Mean-reverting parallel curve shift ``Delta(t)`` with ``Delta(0) = 0``.

    ``sigma`` is the absolute (normal) short-rate volatility from the snapshot.
    """
    return simulate_ou(rng, grid, kappa=kappa, sigma=sigma, n_paths=n_paths, x0=0.0)


def simulate_credit_factor(
    rng: np.random.Generator,
    grid: Sequence[float],
    sigma: float,
    n_paths: int,
    kappa: float = 0.30,
) -> np.ndarray:
    """Log-space mean-reverting factor ``Y(t)`` (spread multiplier ``exp(Y)``).

    ``sigma`` is the lognormal volatility of the credit spread.
    """
    return simulate_ou(rng, grid, kappa=kappa, sigma=sigma, n_paths=n_paths, x0=0.0)


def simulate_fx_spot(
    rng: np.random.Generator,
    grid: Sequence[float],
    s0: float,
    forwards: Sequence[float],
    sigma: float,
    n_paths: int,
) -> np.ndarray:
    """Simulate FX spot by GBM with mean equal to the CIP forward at each node.

    ``forwards[k]`` is the covered-interest-parity forward to ``grid[k]``. The
    path is ``S_k = forwards[k] * exp(-0.5 sigma^2 t_k + sigma W(t_k))`` where
    ``W`` is a standard Brownian motion, so ``E[S_k] = forwards[k]`` exactly.
    """
    times = np.asarray(grid, dtype=float)
    fwd = np.asarray(forwards, dtype=float)
    if len(fwd) != len(times):
        raise ValueError("forwards must align with the time grid")
    steps = _grid_steps(times)
    out = np.empty((n_paths, len(times)), dtype=float)
    w = np.zeros(n_paths)
    for k, dt in enumerate(steps):
        if dt > 0.0:
            w = w + np.sqrt(dt) * rng.standard_normal(n_paths)
        drift = -0.5 * sigma * sigma * times[k]
        out[:, k] = fwd[k] * np.exp(drift + sigma * w)
    return out
