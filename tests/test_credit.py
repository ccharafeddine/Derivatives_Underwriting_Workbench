"""Counterparty credit assessment tests (Session 4). No network required."""

from __future__ import annotations

from math import exp

import pytest

from duw.credit.altman import AltmanZone, altman_z, classify_zone
from duw.credit.merton import merton_from_financials, solve_merton
from duw.credit.public_data import fetch_financials
from duw.credit.rating import (
    DEFAULT_PD_TENORS,
    assess_counterparty,
    pd_term_structure_from_survival,
    pd_to_grade,
)
from duw.data.loader import load_market_snapshot, load_seed_counterparties
from duw.domain.counterparty import Financials
from duw.pricing.curves import SurvivalCurve


def _healthy_financials(**overrides: float) -> Financials:
    base = dict(
        total_assets=5000.0,
        total_liabilities=2000.0,
        current_assets=2500.0,
        current_liabilities=1000.0,
        retained_earnings=1500.0,
        ebit=800.0,
        sales=6000.0,
        market_equity=4000.0,
        equity_volatility=0.25,
    )
    base.update(overrides)
    return Financials(**base)


# --------------------------------------------------------------------------- #
# Merton
# --------------------------------------------------------------------------- #
def test_merton_pd_in_unit_interval() -> None:
    res = solve_merton(
        equity_value=4000.0, equity_vol=0.25, debt=2000.0, risk_free_rate=0.04
    )
    assert 0.0 <= res.pd <= 1.0
    assert res.asset_value > 0.0
    assert res.asset_volatility > 0.0


def test_merton_pd_rises_with_leverage() -> None:
    low = solve_merton(
        equity_value=4000.0, equity_vol=0.25, debt=1000.0, risk_free_rate=0.04
    )
    high = solve_merton(
        equity_value=4000.0, equity_vol=0.25, debt=6000.0, risk_free_rate=0.04
    )
    assert high.pd > low.pd
    assert high.distance_to_default < low.distance_to_default


def test_merton_pd_rises_with_volatility() -> None:
    calm = solve_merton(
        equity_value=4000.0, equity_vol=0.15, debt=3000.0, risk_free_rate=0.04
    )
    wild = solve_merton(
        equity_value=4000.0, equity_vol=0.60, debt=3000.0, risk_free_rate=0.04
    )
    assert wild.pd > calm.pd


def test_merton_solve_converges_for_reasonable_inputs() -> None:
    res = solve_merton(
        equity_value=4000.0, equity_vol=0.25, debt=2000.0, risk_free_rate=0.04
    )
    assert res.converged is True
    # Asset value is close to equity plus the discounted debt.
    expected = 4000.0 + 2000.0 * exp(-0.04)
    assert res.asset_value == pytest.approx(expected, rel=0.1)


def test_merton_degenerate_inputs_fall_back() -> None:
    res = solve_merton(
        equity_value=0.0, equity_vol=0.25, debt=2000.0, risk_free_rate=0.04
    )
    assert res.converged is False
    assert res.pd == pytest.approx(1.0)


def test_merton_from_financials() -> None:
    res = merton_from_financials(_healthy_financials(), risk_free_rate=0.04)
    assert 0.0 <= res.pd < 0.5  # a healthy name is unlikely to default in 1y


# --------------------------------------------------------------------------- #
# Altman
# --------------------------------------------------------------------------- #
def test_altman_zone_thresholds() -> None:
    assert classify_zone(3.5) is AltmanZone.SAFE
    assert classify_zone(2.5) is AltmanZone.GREY
    assert classify_zone(1.0) is AltmanZone.DISTRESS


def test_altman_healthy_is_safe() -> None:
    res = altman_z(_healthy_financials())
    assert res.zone is AltmanZone.SAFE
    assert res.z_score > 2.99
    # Component math: X4 = market equity / total liabilities.
    assert res.x4 == pytest.approx(4000.0 / 2000.0)


def test_altman_distressed_is_distress() -> None:
    distressed = _healthy_financials(
        total_liabilities=4800.0,
        current_assets=900.0,
        current_liabilities=1800.0,
        retained_earnings=-500.0,
        ebit=50.0,
        sales=1200.0,
        market_equity=300.0,
    )
    res = altman_z(distressed)
    assert res.zone is AltmanZone.DISTRESS
    assert res.z_score < 1.81


def test_altman_rejects_nonpositive_assets() -> None:
    with pytest.raises(ValueError):
        altman_z(_healthy_financials(total_assets=0.0))


# --------------------------------------------------------------------------- #
# Rating and PD term structure
# --------------------------------------------------------------------------- #
def test_pd_to_grade_mapping() -> None:
    assert pd_to_grade(0.00005) == "AAA"
    assert pd_to_grade(0.0012) == "A"
    assert pd_to_grade(0.003) == "BBB"
    assert pd_to_grade(0.01) == "BB"
    assert pd_to_grade(0.05) == "B"
    assert pd_to_grade(0.9) == "D"
    # Monotone: worse PD never maps to a better grade position.
    grades = [pd_to_grade(p) for p in (1e-5, 1e-3, 1e-2, 1e-1, 0.9)]
    assert grades == ["AAA", "A", "BB", "B", "D"]


def test_pd_term_structure_is_monotone() -> None:
    snap = load_market_snapshot()
    surv = SurvivalCurve.bootstrap(snap.credit("ACME"))
    term = pd_term_structure_from_survival(surv)
    tenors = [t for t, _ in term]
    pds = [pd for _, pd in term]
    assert tenors == list(DEFAULT_PD_TENORS)
    assert all(0.0 <= p <= 1.0 for p in pds)
    assert all(later >= earlier for earlier, later in zip(pds, pds[1:], strict=False))


def test_assess_counterparty_with_cds() -> None:
    snap = load_market_snapshot()
    cps = {c.counterparty_id: c for c in load_seed_counterparties()}
    profile = assess_counterparty(cps["CP001"], snap)  # CP001 has CDS issuer ACME
    assert profile.counterparty_id == "CP001"
    assert profile.merton_pd is not None
    assert profile.altman_z is not None
    assert profile.internal_grade is not None
    # CDS present -> term structure reported at the default tenors, monotone.
    tenors = [t for t, _ in profile.pd_term_structure]
    assert tenors == list(DEFAULT_PD_TENORS)
    pds = [pd for _, pd in profile.pd_term_structure]
    assert all(later >= earlier for earlier, later in zip(pds, pds[1:], strict=False))


def test_assess_counterparty_without_cds_uses_merton() -> None:
    snap = load_market_snapshot()
    cps = {c.counterparty_id: c for c in load_seed_counterparties()}
    # CP004 has financials but no CDS issuer -> Merton-implied term structure.
    profile = assess_counterparty(cps["CP004"], snap)
    assert profile.merton_pd is not None
    assert len(profile.pd_term_structure) == len(DEFAULT_PD_TENORS)
    pds = [pd for _, pd in profile.pd_term_structure]
    assert all(later >= earlier for earlier, later in zip(pds, pds[1:], strict=False))


# --------------------------------------------------------------------------- #
# Public data (offline behavior)
# --------------------------------------------------------------------------- #
def test_fetch_financials_none_ticker_is_none_without_network() -> None:
    assert fetch_financials(None) is None
    assert fetch_financials("") is None
    assert fetch_financials("   ") is None
