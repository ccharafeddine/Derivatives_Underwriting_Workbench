"""CVA/DVA and collateral (CSA) tests (Session 5)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from duw.data.loader import load_market_snapshot
from duw.domain.instruments import IRS, NettingSet, SwapDirection
from duw.domain.market import CreditCurve
from duw.pricing.curves import DiscountCurve, SurvivalCurve
from duw.risk.collateral import CSA, apply_csa, compute_collateral
from duw.risk.cva import (
    compute_bcva,
    compute_cva,
    compute_fva,
    expected_exposures_from_cube,
    wrong_way_adjusted_ee,
)
from duw.risk.exposure import ExposureEngine

AS_OF = date(2025, 6, 30)


def _usd_curve() -> DiscountCurve:
    return DiscountCurve.from_yield_curve(load_market_snapshot().curve("USD"))


def _survival(spread: float) -> SurvivalCurve:
    cc = CreditCurve(
        issuer="X",
        tenors=(0.5, 1.0, 2.0, 3.0, 5.0),
        spreads=(spread,) * 5,
        recovery_rate=0.4,
    )
    return SurvivalCurve.bootstrap(cc)


def _flat_ee(level: float, grid: tuple[float, ...]) -> np.ndarray:
    return np.full(len(grid), level)


# --------------------------------------------------------------------------- #
# CVA / DVA
# --------------------------------------------------------------------------- #
def test_cva_is_positive_for_positive_exposure() -> None:
    grid = (0.0, 1.0, 2.0, 3.0, 5.0)
    ee = _flat_ee(1_000_000.0, grid)
    cva, contrib = compute_cva(grid, ee, _usd_curve(), _survival(0.01), lgd=0.6)
    assert cva > 0.0
    assert contrib[0] == 0.0  # first interval starts at t_0
    assert contrib.sum() == pytest.approx(cva)


def test_cva_rises_with_pd() -> None:
    grid = (0.0, 1.0, 2.0, 3.0, 5.0)
    ee = _flat_ee(1_000_000.0, grid)
    tight, _ = compute_cva(grid, ee, _usd_curve(), _survival(0.005), lgd=0.6)
    wide, _ = compute_cva(grid, ee, _usd_curve(), _survival(0.030), lgd=0.6)
    assert wide > tight


def test_cva_scales_with_exposure() -> None:
    grid = (0.0, 1.0, 2.0, 3.0, 5.0)
    curve, surv = _usd_curve(), _survival(0.01)
    base, _ = compute_cva(grid, _flat_ee(1_000_000.0, grid), curve, surv, lgd=0.6)
    doubled, _ = compute_cva(grid, _flat_ee(2_000_000.0, grid), curve, surv, lgd=0.6)
    assert doubled == pytest.approx(2.0 * base, rel=1e-9)


def test_dva_symmetric_with_cva() -> None:
    # Identical exposure, curve, and LGD on both legs -> DVA equals CVA, BCVA 0.
    grid = (0.0, 1.0, 2.0, 3.0, 5.0)
    exposures = _flat_ee(1_000_000.0, grid)
    surv = _survival(0.015)
    result = compute_bcva(
        grid,
        ee=exposures,
        ene=exposures,
        discount_curve=_usd_curve(),
        cp_survival=surv,
        cp_lgd=0.6,
        own_survival=surv,
        own_lgd=0.6,
    )
    assert result.dva == pytest.approx(result.cva)
    assert result.bcva == pytest.approx(0.0)


def test_bcva_defaults_to_cva_without_own_curve() -> None:
    grid = (0.0, 1.0, 3.0, 5.0)
    ee = _flat_ee(500_000.0, grid)
    result = compute_bcva(
        grid,
        ee=ee,
        ene=ee,
        discount_curve=_usd_curve(),
        cp_survival=_survival(0.02),
        cp_lgd=0.6,
    )
    assert result.dva == 0.0
    assert result.bcva == pytest.approx(result.cva)


def test_wrong_way_adjusted_ee_tilts_with_correlation() -> None:
    # A cube with a spread of positive exposures across paths.
    cube = np.array(
        [[0.0, 100.0], [0.0, 300.0], [0.0, 500.0], [0.0, 900.0]], dtype=float
    )
    plain = wrong_way_adjusted_ee(cube, 0.0)
    assert plain[1] == pytest.approx(cube[:, 1].mean())  # rho=0 -> mean EE
    wrong = wrong_way_adjusted_ee(cube, 0.6)
    right = wrong_way_adjusted_ee(cube, -0.6)
    # Wrong-way tilts EE up (toward high-exposure paths); right-way down.
    assert wrong[1] > plain[1] > right[1]


def test_wrong_way_risk_raises_cva() -> None:
    grid = (0.0, 1.0, 2.0, 3.0, 5.0)
    cube = np.array(
        [[0.0, 100.0, 150.0, 120.0, 0.0]] * 1 + [[0.0, 800.0, 900.0, 700.0, 0.0]] * 1,
        dtype=float,
    )
    curve, surv = _usd_curve(), _survival(0.02)
    ee_indep = wrong_way_adjusted_ee(cube, 0.0)
    ee_wwr = wrong_way_adjusted_ee(cube, 0.8)
    cva_indep, _ = compute_cva(grid, ee_indep, curve, surv, lgd=0.6)
    cva_wwr, _ = compute_cva(grid, ee_wwr, curve, surv, lgd=0.6)
    assert cva_wwr > cva_indep


def test_fva_scales_with_funding_spread() -> None:
    grid = (0.0, 1.0, 2.0, 3.0, 5.0)
    ee = _flat_ee(1_000_000.0, grid)
    ene = _flat_ee(200_000.0, grid)
    curve = _usd_curve()
    assert compute_fva(grid, ee, ene, curve, 0.0) == 0.0
    fva = compute_fva(grid, ee, ene, curve, 0.01)
    assert fva > 0.0  # positive net exposure funded at a positive spread
    assert compute_fva(grid, ee, ene, curve, 0.02) == pytest.approx(2.0 * fva)


def test_bcva_includes_fva_and_records_wwr() -> None:
    grid = (0.0, 1.0, 3.0, 5.0)
    ee = _flat_ee(500_000.0, grid)
    result = compute_bcva(
        grid,
        ee=ee,
        ene=_flat_ee(100_000.0, grid),
        discount_curve=_usd_curve(),
        cp_survival=_survival(0.02),
        cp_lgd=0.6,
        funding_spread=0.008,
        wwr_correlation=0.3,
    )
    assert result.fva > 0.0
    assert result.wwr_correlation == 0.3


# --------------------------------------------------------------------------- #
# Collateral (CSA)
# --------------------------------------------------------------------------- #
def _exposure_cube() -> tuple[np.ndarray, tuple[float, ...]]:
    irs = IRS(
        trade_id="IRS1",
        counterparty_id="CP001",
        notional=10_000_000.0,
        currency="USD",
        trade_date=AS_OF,
        maturity_date=date(2030, 6, 30),
        fixed_rate=0.043,
        direction=SwapDirection.PAY_FIXED,
    )
    ns = NettingSet(netting_set_id="NS1", counterparty_id="CP001", trades=(irs,))
    engine = ExposureEngine(ns, load_market_snapshot())
    grid = engine.build_time_grid(8)
    cube = engine.simulate_cube(grid, n_paths=1500, seed=3)
    return cube, grid


def test_no_csa_recovers_uncollateralized() -> None:
    cube, grid = _exposure_cube()
    # Huge threshold, no IM -> nothing is collateralized.
    open_csa = CSA(threshold=1e15, mta=0.0, initial_margin=0.0, mpor_days=10)
    collat = apply_csa(cube, grid, open_csa)
    assert np.allclose(collat, np.maximum(cube, 0.0))


def test_tighter_threshold_reduces_exposure() -> None:
    cube, grid = _exposure_cube()
    loose = compute_collateral(cube, grid, CSA(threshold=1_000_000.0))
    tight = compute_collateral(cube, grid, CSA(threshold=100_000.0))
    assert tight.peak_pfe_collateralized < loose.peak_pfe_collateralized
    assert tight.peak_pfe_collateralized <= tight.peak_pfe_uncollateralized


def test_initial_margin_reduces_exposure() -> None:
    cube, grid = _exposure_cube()
    without_im = compute_collateral(cube, grid, CSA(threshold=200_000.0))
    with_im = compute_collateral(
        cube, grid, CSA(threshold=200_000.0, initial_margin=150_000.0)
    )
    assert with_im.peak_pfe_collateralized <= without_im.peak_pfe_collateralized
    assert sum(with_im.ee_collateralized) <= sum(without_im.ee_collateralized)


def test_tighter_csa_reduces_cva() -> None:
    cube, grid = _exposure_cube()
    curve, surv = _usd_curve(), _survival(0.02)
    ee_uncollat, _ = expected_exposures_from_cube(cube)
    ee_collat = np.asarray(
        compute_collateral(cube, grid, CSA(threshold=100_000.0)).ee_collateralized
    )
    cva_uncollat, _ = compute_cva(grid, ee_uncollat, curve, surv, lgd=0.6)
    cva_collat, _ = compute_cva(grid, ee_collat, curve, surv, lgd=0.6)
    assert cva_collat < cva_uncollat


def test_collateral_result_echoes_csa_parameters() -> None:
    cube, grid = _exposure_cube()
    csa = CSA(threshold=250_000.0, mta=50_000.0, initial_margin=100_000.0, mpor_days=10)
    result = compute_collateral(cube, grid, csa)
    assert result.threshold == 250_000.0
    assert result.mta == 50_000.0
    assert result.initial_margin == 100_000.0
    assert result.mpor_days == 10
    assert len(result.ee_collateralized) == len(grid)
