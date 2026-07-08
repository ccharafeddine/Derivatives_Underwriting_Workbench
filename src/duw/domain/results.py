"""Analysis results.

The mutable :class:`AnalysisResults` aggregate threaded through the pipeline,
plus one frozen sub-result dataclass per producing step. Every sub-result field
defaults to an empty/``nan``/``None`` value so the containers can be constructed
now and filled by later sessions; :class:`AnalysisResults` holds each as
``None`` until its step runs.

No Qt imports.

Unit conventions:

- Exposure amounts are in the netting set's currency, non-negative.
- ``time_grid`` entries are year fractions from the as-of date.
- CVA/DVA/BCVA are present-value amounts; ``lgd`` is a decimal in ``[0, 1]``.
- ``utilization`` is a decimal fraction of the limit (``1.0`` == 100%).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import nan
from typing import Any

from duw.domain.counterparty import Counterparty, CreditProfile
from duw.domain.instruments import NettingSet
from duw.domain.market import MarketSnapshot


@dataclass(frozen=True)
class ExposureProfile:
    """Exposure metrics over the time grid (Step 6).

    ``ee``/``pfe_95``/``pfe_99`` are aligned index-for-index with ``time_grid``.
    ``epe`` is the time-average of ``ee``; ``peak_pfe`` is the max of the 95%
    PFE over the grid, attained at ``peak_pfe_time``.
    """

    time_grid: tuple[float, ...] = field(default_factory=tuple)
    ee: tuple[float, ...] = field(default_factory=tuple)
    epe: float = nan
    pfe_95: tuple[float, ...] = field(default_factory=tuple)
    pfe_99: tuple[float, ...] = field(default_factory=tuple)
    peak_pfe: float = nan
    peak_pfe_time: float = nan


@dataclass(frozen=True)
class CollateralResult:
    """Collateralized vs uncollateralized exposure under a CSA (Step 7).

    CSA parameters are echoed for the memo; the ``*_uncollateralized`` figures
    mirror the plain :class:`ExposureProfile`, and the ``*_collateralized``
    figures apply threshold / MTA / initial margin over the margin period of
    risk.
    """

    threshold: float = nan
    mta: float = nan
    initial_margin: float = nan
    mpor_days: int = 0
    collateral_currency: str = ""
    fx_haircut: float = 0.0
    time_grid: tuple[float, ...] = field(default_factory=tuple)
    ee_uncollateralized: tuple[float, ...] = field(default_factory=tuple)
    ee_collateralized: tuple[float, ...] = field(default_factory=tuple)
    peak_pfe_uncollateralized: float = nan
    peak_pfe_collateralized: float = nan


@dataclass(frozen=True)
class CVAResult:
    """Credit / debit / funding valuation adjustments (Step 8).

    ``bcva`` == ``cva`` − ``dva``. ``fva`` is the funding valuation adjustment
    (0 when no funding spread is set). ``wwr_correlation`` is the exposure-credit
    correlation used for wrong-way risk (0 = independence). ``contributions`` is
    an optional per-interval breakdown aligned with ``time_grid`` for charting.
    """

    cva: float = nan
    dva: float = nan
    bcva: float = nan
    fva: float = 0.0
    lgd: float = nan
    wwr_correlation: float = 0.0
    time_grid: tuple[float, ...] = field(default_factory=tuple)
    contributions: tuple[float, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class LimitCheck:
    """Limit utilization for the proposed trade (Step 9).

    ``incremental_peak_pfe`` is the peak PFE with the proposed trade minus the
    peak PFE of the existing set. ``breach`` is set when the proposed trade
    pushes ``utilization`` above 1.0.
    """

    limit: float = nan
    current_peak_pfe: float = nan
    proposed_peak_pfe: float = nan
    incremental_peak_pfe: float = nan
    utilization: float = nan
    headroom: float = nan
    breach: bool = False


@dataclass(frozen=True)
class MemoResult:
    """Paths to the generated memo artifacts (Steps 10–11)."""

    html_path: str | None = None
    pdf_path: str | None = None
    pptx_path: str | None = None
    recommendation: str | None = None


@dataclass
class AnalysisResults:
    """Mutable aggregate threaded through the pipeline.

    The orchestrator constructs one of these and each step fills in its slice.
    ``run_config`` carries the reproducibility inputs (Monte Carlo seed, path
    count, grid, confidence levels, LGD, ...) and is saved alongside the run.
    ``messages`` accumulates a short human-readable log of each step.
    """

    run_config: dict[str, Any] = field(default_factory=dict)
    snapshot: MarketSnapshot | None = None
    counterparty: Counterparty | None = None
    netting_set: NettingSet | None = None
    credit_profile: CreditProfile | None = None
    # The net-MtM cube (paths x grid dates) kept so the UI can recompute
    # collateral for a new CSA without re-running the Monte Carlo. Typed loosely
    # (a numpy array) to avoid a hard numpy annotation in the domain layer.
    net_mtm_cube: Any = None
    exposure: ExposureProfile | None = None
    collateral: CollateralResult | None = None
    cva: CVAResult | None = None
    limits: LimitCheck | None = None
    memo: MemoResult | None = None
    messages: list[str] = field(default_factory=list)

    def log(self, message: str) -> None:
        """Append a step message to the run log."""
        self.messages.append(message)
