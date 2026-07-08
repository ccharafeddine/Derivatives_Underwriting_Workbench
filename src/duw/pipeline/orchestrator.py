"""Pipeline orchestrator.

Runs the underwriting analysis as a sequential pipeline, threading a single
:class:`AnalysisResults` through each step. Given a :class:`RunConfig` (which
carries the Monte Carlo seed and every other reproducibility input), the
counterparty, its existing netting set, and the proposed trade, it produces a
fully populated result.

Steps 0-9 are implemented here; steps 3-5 (simulate / reprice / aggregate) are
performed together by :meth:`ExposureEngine.simulate_cube`, which returns the
net-MtM cube directly. Step 10 (memo) is a documented hook left for Session 10;
step 11 (save) writes the run config as JSON when an output directory is given,
so any run is reproducible.

Progress is reported through an optional callback ``(fraction, message)``. This
module is Qt-free; the background worker in ``worker.py`` is the only Qt piece.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from math import log
from pathlib import Path

from duw.credit.rating import assess_counterparty
from duw.data.loader import load_market_snapshot
from duw.domain.counterparty import Counterparty, CreditProfile
from duw.domain.instruments import NettingSet, Trade
from duw.domain.market import MarketSnapshot
from duw.domain.results import AnalysisResults, MemoResult
from duw.pricing.curves import DiscountCurve, SurvivalCurve
from duw.risk.collateral import CSA, compute_collateral
from duw.risk.cva import (
    compute_bcva,
    constant_hazard_survival,
    expected_exposures_from_cube,
)
from duw.risk.exposure import ExposureEngine
from duw.risk.limits import limit_check_from_peaks

# A very large threshold that leaves exposure entirely uncollateralized.
_OPEN_CSA_THRESHOLD = 1e15

ProgressCallback = Callable[[float, str], None]


@dataclass(frozen=True)
class RunConfig:
    """Reproducibility inputs for one underwriting run.

    Every field is a plain scalar/tuple so the config serializes to JSON and a
    saved run can be replayed exactly. ``csa_threshold`` of ``None`` means no
    CSA (exposure is left uncollateralized).
    """

    seed: int = 12345
    n_paths: int = 2000
    n_steps: int = 12
    horizon: float = 1.0
    lgd: float = 0.6
    own_credit_spread: float = 0.004
    own_recovery: float = 0.4
    csa_threshold: float | None = None
    csa_mta: float = 0.0
    csa_initial_margin: float = 0.0
    csa_mpor_days: int = 10
    limit: float = 5_000_000.0
    kappa_rate: float = 0.10
    kappa_credit: float = 0.30
    credit_vol: float = 0.50
    confidence_levels: tuple[float, float] = (0.95, 0.99)


# The eleven pipeline steps, for progress reporting.
_STEPS: tuple[str, ...] = (
    "Load market snapshot",
    "Build trade and netting set",
    "Assess counterparty credit",
    "Simulate risk factors",
    "Reprice across the time grid",
    "Aggregate the netting set",
    "Compute the exposure profile",
    "Apply collateral (CSA)",
    "Compute CVA / DVA / BCVA",
    "Check limits",
    "Interpret and generate memo",
    "Save outputs",
)


class Orchestrator:
    """Runs the sequential underwriting pipeline into an ``AnalysisResults``."""

    def __init__(
        self,
        config: RunConfig | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self.config = config or RunConfig()
        self._progress = progress_callback

    def _emit(self, step_index: int, message: str) -> None:
        if self._progress is not None:
            self._progress((step_index + 1) / len(_STEPS), message)

    def run(
        self,
        counterparty: Counterparty,
        existing_set: NettingSet,
        proposed_trade: Trade,
        *,
        snapshot: MarketSnapshot | None = None,
        output_dir: str | Path | None = None,
    ) -> AnalysisResults:
        """Execute the pipeline and return the populated results."""
        cfg = self.config
        results = AnalysisResults(run_config=asdict(cfg))

        # Step 0 — load market snapshot (offline bundled default).
        self._emit(0, _STEPS[0])
        snapshot = snapshot or load_market_snapshot()
        results.snapshot = snapshot
        results.log(f"Loaded market snapshot as of {snapshot.as_of.isoformat()}")

        # Step 1 — build the proposed netting set.
        self._emit(1, _STEPS[1])
        proposed_set = existing_set.add_trade(proposed_trade)
        results.netting_set = proposed_set
        results.log(
            f"Netting set has {len(proposed_set)} trade(s) after the proposed trade"
        )

        # Step 2 — assess counterparty credit.
        self._emit(2, _STEPS[2])
        profile = assess_counterparty(counterparty, snapshot, horizon=cfg.horizon)
        results.credit_profile = profile
        results.log(
            f"Counterparty grade {profile.internal_grade}, "
            f"Altman zone {profile.altman_zone}"
        )

        # Steps 3-5 — simulate, reprice, aggregate into the net-MtM cube.
        self._emit(3, _STEPS[3])
        engine = ExposureEngine(
            proposed_set,
            snapshot,
            kappa_rate=cfg.kappa_rate,
            kappa_credit=cfg.kappa_credit,
            credit_vol=cfg.credit_vol,
        )
        grid = engine.build_time_grid(cfg.n_steps)
        cube = engine.simulate_cube(grid, n_paths=cfg.n_paths, seed=cfg.seed)
        results.net_mtm_cube = cube
        self._emit(4, _STEPS[4])
        self._emit(5, _STEPS[5])
        results.log(
            f"Simulated {cfg.n_paths} paths over {len(grid)} grid dates "
            f"(seed {cfg.seed})"
        )

        # Step 6 — exposure profile.
        self._emit(6, _STEPS[6])
        exposure = engine.profile_from_cube(cube, grid)
        results.exposure = exposure
        results.log(
            f"Peak PFE(95%) {exposure.peak_pfe:,.0f} at "
            f"t={exposure.peak_pfe_time:.2f}y; EPE {exposure.epe:,.0f}"
        )

        # Step 7 — collateral (CSA).
        self._emit(7, _STEPS[7])
        csa = self._build_csa(cfg)
        collateral = compute_collateral(cube, grid, csa)
        results.collateral = collateral
        results.log(
            f"Collateralized peak PFE {collateral.peak_pfe_collateralized:,.0f} "
            f"vs uncollateralized {collateral.peak_pfe_uncollateralized:,.0f}"
        )

        # Step 8 — CVA / DVA / BCVA.
        self._emit(8, _STEPS[8])
        results.cva = self._compute_cva(
            cfg, counterparty, profile, snapshot, proposed_set, cube, grid
        )
        results.log(
            f"CVA {results.cva.cva:,.0f}, DVA {results.cva.dva:,.0f}, "
            f"BCVA {results.cva.bcva:,.0f}"
        )

        # Step 9 — limit check (existing subset repriced on the same paths).
        self._emit(9, _STEPS[9])
        existing_cube = engine.simulate_cube(
            grid, n_paths=cfg.n_paths, seed=cfg.seed, trades=existing_set.trades
        )
        current_peak = engine.profile_from_cube(existing_cube, grid).peak_pfe
        limits = limit_check_from_peaks(cfg.limit, current_peak, exposure.peak_pfe)
        results.limits = limits
        results.log(
            f"Limit utilization {limits.utilization:.0%}"
            + (" — BREACH" if limits.breach else "")
        )

        # Step 10 — interpret + memo (hook for Session 10).
        self._emit(10, _STEPS[10])
        results.memo = MemoResult()  # populated by the reports session
        results.log("Memo generation is deferred to a later session")

        # Step 11 — save the run config for reproducibility.
        self._emit(11, _STEPS[11])
        if output_dir is not None:
            saved = self.save_run_config(results, output_dir)
            results.log(f"Saved run config to {saved}")

        return results

    # -- helpers ----------------------------------------------------------- #
    @staticmethod
    def _build_csa(cfg: RunConfig) -> CSA:
        threshold = (
            _OPEN_CSA_THRESHOLD if cfg.csa_threshold is None else cfg.csa_threshold
        )
        return CSA(
            threshold=threshold,
            mta=cfg.csa_mta,
            initial_margin=cfg.csa_initial_margin,
            mpor_days=cfg.csa_mpor_days,
        )

    def _reporting_currency(self, netting_set: NettingSet) -> str:
        currencies = netting_set.currencies
        return currencies[0] if currencies else "USD"

    def _compute_cva(
        self,
        cfg: RunConfig,
        counterparty: Counterparty,
        profile: CreditProfile,
        snapshot: MarketSnapshot,
        netting_set: NettingSet,
        cube,
        grid,
    ):
        ccy = self._reporting_currency(netting_set)
        try:
            discount_curve = DiscountCurve.from_yield_curve(snapshot.curve(ccy))
        except KeyError:
            discount_curve = DiscountCurve.from_yield_curve(
                next(iter(snapshot.discount_curves.values()))
            )

        # Counterparty survival: from its CDS curve if it trades, else from the
        # assessed PD term structure via cumulative hazard.
        if counterparty.cds_issuer in snapshot.credit_curves:
            credit_curve = snapshot.credit(counterparty.cds_issuer)
            cp_survival = SurvivalCurve.bootstrap(credit_curve)
            cp_lgd = 1.0 - credit_curve.recovery_rate
        else:
            cp_survival = self._survival_from_profile(profile, cfg)
            cp_lgd = cfg.lgd

        own_survival = None
        own_lgd = 0.0
        if cfg.own_credit_spread > 0.0:
            own_survival = constant_hazard_survival(
                cfg.own_credit_spread, recovery=cfg.own_recovery
            )
            own_lgd = 1.0 - cfg.own_recovery

        ee, ene = expected_exposures_from_cube(cube)
        return compute_bcva(
            grid, ee, ene, discount_curve, cp_survival, cp_lgd, own_survival, own_lgd
        )

    @staticmethod
    def _survival_from_profile(profile: CreditProfile, cfg: RunConfig) -> SurvivalCurve:
        """Build a survival curve from the assessed PD term structure.

        Converts cumulative PDs to cumulative hazards ``H(t) = -ln(1 - PD(t))``
        and constructs the curve directly.
        """
        term = profile.pd_term_structure
        if not term:
            # No credit information at all: assume a flat, benign hazard.
            return constant_hazard_survival(0.005, recovery=1.0 - cfg.lgd)
        tenors = tuple(t for t, _ in term)
        cum_hazard = tuple(-log(max(1.0 - pd, 1e-12)) for _, pd in term)
        return SurvivalCurve(tenors, cum_hazard)

    @staticmethod
    def save_run_config(results: AnalysisResults, output_dir: str | Path) -> Path:
        """Write the run config plus a scalar results summary to JSON."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = out / "run_config.json"
        payload = {
            "run_config": results.run_config,
            "summary": _results_summary(results),
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path


def _results_summary(results: AnalysisResults) -> dict:
    """A small, JSON-serializable summary of the run's headline numbers."""
    summary: dict[str, object] = {}
    if results.exposure is not None:
        summary["peak_pfe"] = results.exposure.peak_pfe
        summary["epe"] = results.exposure.epe
    if results.cva is not None:
        summary["cva"] = results.cva.cva
        summary["dva"] = results.cva.dva
        summary["bcva"] = results.cva.bcva
    if results.limits is not None:
        summary["utilization"] = results.limits.utilization
        summary["breach"] = results.limits.breach
    if results.credit_profile is not None:
        summary["internal_grade"] = results.credit_profile.internal_grade
    return summary


def run_pipeline(
    counterparty: Counterparty,
    existing_set: NettingSet,
    proposed_trade: Trade,
    config: RunConfig | None = None,
    *,
    snapshot: MarketSnapshot | None = None,
    output_dir: str | Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> AnalysisResults:
    """Convenience wrapper: build an :class:`Orchestrator` and run it once."""
    orchestrator = Orchestrator(config, progress_callback=progress_callback)
    return orchestrator.run(
        counterparty,
        existing_set,
        proposed_trade,
        snapshot=snapshot,
        output_dir=output_dir,
    )
