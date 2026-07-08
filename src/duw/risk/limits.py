"""Per-counterparty limit checks.

Checks a proposed trade against a counterparty credit limit expressed on peak
potential future exposure (PFE). The check reports:

- **current peak PFE** — peak PFE of the existing netting set (0 if empty).
- **proposed peak PFE** — peak PFE of the existing set plus the proposed trade.
- **incremental peak PFE** — proposed minus current: the exposure the new trade
  adds. Both legs are repriced on the *same* simulated factor paths (one engine,
  one seed, one grid), so the difference is a consistent marginal rather than a
  difference of two independent Monte Carlo runs.
- **utilization** — proposed peak PFE / limit.
- **headroom** — limit minus proposed peak PFE.
- **breach** — set when the proposed trade pushes utilization above 1.0.

The proposed set defines the horizon (the union of existing and proposed
maturities), and both legs use that grid so peaks are comparable. Pure numerics;
no Qt.
"""

from __future__ import annotations

from dataclasses import dataclass

from duw.domain.instruments import NettingSet, Trade
from duw.domain.market import MarketSnapshot
from duw.domain.results import LimitCheck
from duw.risk.exposure import ExposureEngine


@dataclass(frozen=True)
class Limit:
    """A per-counterparty PFE-based credit limit, in the reporting currency."""

    counterparty_id: str
    amount: float


def check_limit(
    existing_set: NettingSet,
    proposed_trade: Trade,
    snapshot: MarketSnapshot,
    limit: float | Limit,
    *,
    n_paths: int = 2000,
    seed: int = 12345,
    n_steps: int = 12,
    engine_kwargs: dict | None = None,
) -> LimitCheck:
    """Check ``proposed_trade`` against ``limit`` for the counterparty.

    ``existing_set`` may be empty, in which case the proposed trade is the whole
    set and the incremental PFE equals its standalone peak PFE.
    """
    limit_amount = limit.amount if isinstance(limit, Limit) else float(limit)

    proposed_set = existing_set.add_trade(proposed_trade)
    engine = ExposureEngine(proposed_set, snapshot, **(engine_kwargs or {}))
    grid = engine.build_time_grid(n_steps)

    # Reprice the full set and the existing subset on identical factor paths.
    proposed_cube = engine.simulate_cube(grid, n_paths=n_paths, seed=seed)
    existing_cube = engine.simulate_cube(
        grid, n_paths=n_paths, seed=seed, trades=existing_set.trades
    )

    proposed_peak = engine.profile_from_cube(proposed_cube, grid).peak_pfe
    current_peak = engine.profile_from_cube(existing_cube, grid).peak_pfe
    return limit_check_from_peaks(limit_amount, current_peak, proposed_peak)


def limit_check_from_peaks(
    limit_amount: float, current_peak_pfe: float, proposed_peak_pfe: float
) -> LimitCheck:
    """Assemble a :class:`LimitCheck` from precomputed peak-PFE figures.

    Shared by :func:`check_limit` and the pipeline orchestrator so the
    utilization / headroom / breach reconciliation lives in one place.
    """
    incremental = proposed_peak_pfe - current_peak_pfe
    utilization = (
        proposed_peak_pfe / limit_amount if limit_amount > 0.0 else float("inf")
    )
    headroom = limit_amount - proposed_peak_pfe
    return LimitCheck(
        limit=limit_amount,
        current_peak_pfe=current_peak_pfe,
        proposed_peak_pfe=proposed_peak_pfe,
        incremental_peak_pfe=incremental,
        utilization=utilization,
        headroom=headroom,
        breach=utilization > 1.0,
    )
