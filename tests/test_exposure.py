"""Risk-factor simulation and exposure engine tests (Session 3)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import numpy as np
import pytest

from duw.data.loader import load_market_snapshot
from duw.domain.instruments import (
    CDS,
    IRS,
    CdsDirection,
    FxDirection,
    FXForward,
    NettingSet,
    SwapDirection,
)
from duw.pricing.curves import DiscountCurve
from duw.pricing.fx_forward import forward_rate_fx, price_fx_forward
from duw.risk.exposure import ExposureEngine, MixedCurrencyError
from duw.risk.simulators import simulate_fx_spot, simulate_ou, simulate_rate_shift

AS_OF = date(2025, 6, 30)


# --------------------------------------------------------------------------- #
# Simulators
# --------------------------------------------------------------------------- #
def test_ou_is_reproducible_for_fixed_seed() -> None:
    grid = (0.0, 0.5, 1.0, 2.0)
    a = simulate_ou(np.random.default_rng(7), grid, kappa=0.2, sigma=0.01, n_paths=100)
    b = simulate_ou(np.random.default_rng(7), grid, kappa=0.2, sigma=0.01, n_paths=100)
    assert np.array_equal(a, b)


def test_ou_starts_at_x0() -> None:
    grid = (0.0, 1.0)
    paths = simulate_ou(
        np.random.default_rng(1), grid, kappa=0.2, sigma=0.01, n_paths=50, x0=0.0
    )
    # First column is time 0 -> all paths equal the start state.
    assert np.allclose(paths[:, 0], 0.0)
    # The factor actually moves by the next node.
    assert paths[:, 1].std() > 0.0


def test_rate_shift_variance_grows_then_stabilizes() -> None:
    grid = (0.5, 1.0, 5.0, 20.0)
    paths = simulate_rate_shift(
        np.random.default_rng(3), grid, sigma=0.01, n_paths=5000, kappa=0.2
    )
    stds = paths.std(axis=0)
    # Mean-reverting: variance increases early and levels off (stationary).
    assert stds[0] < stds[1] < stds[2]
    assert stds[3] == pytest.approx(stds[2], rel=0.15)


def test_fx_spot_mean_matches_forward() -> None:
    snap = load_market_snapshot()
    base = DiscountCurve.from_yield_curve(snap.curve("EUR"))
    quote = DiscountCurve.from_yield_curve(snap.curve("USD"))
    spot0 = snap.fx("EURUSD")
    grid = (0.25, 1.0, 3.0)
    forwards = [forward_rate_fx(spot0, base, quote, t) for t in grid]
    paths = simulate_fx_spot(
        np.random.default_rng(11),
        grid,
        s0=spot0,
        forwards=forwards,
        sigma=0.09,
        n_paths=40000,
    )
    means = paths.mean(axis=0)
    for m, f in zip(means, forwards, strict=True):
        assert m == pytest.approx(f, rel=0.02)


# --------------------------------------------------------------------------- #
# Exposure engine
# --------------------------------------------------------------------------- #
def _irs_netting_set() -> NettingSet:
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
    return NettingSet(netting_set_id="NS1", counterparty_id="CP001", trades=(irs,))


def _mixed_netting_set() -> NettingSet:
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
    fx = FXForward(
        trade_id="FX1",
        counterparty_id="CP001",
        notional=8_000_000.0,
        currency="USD",
        trade_date=AS_OF,
        maturity_date=date(2027, 6, 30),
        base_currency="EUR",
        quote_currency="USD",
        contract_rate=1.10,
        direction=FxDirection.BUY_BASE,
    )
    cds = CDS(
        trade_id="CDS1",
        counterparty_id="CP001",
        notional=5_000_000.0,
        currency="USD",
        trade_date=AS_OF,
        maturity_date=date(2030, 6, 30),
        reference_entity="ACME",
        direction=CdsDirection.BUY_PROTECTION,
        spread=0.010,
    )
    return NettingSet(
        netting_set_id="NS2", counterparty_id="CP001", trades=(irs, fx, cds)
    )


def test_exposure_non_negative_and_pfe_dominates_where_likely() -> None:
    engine = ExposureEngine(_irs_netting_set(), load_market_snapshot())
    grid = engine.build_time_grid(8)
    cube = engine.simulate_cube(grid, n_paths=2000, seed=42)
    exposure = np.maximum(cube, 0.0)
    ee = exposure.mean(axis=0)
    p95 = np.percentile(exposure, 95.0, axis=0)
    p99 = np.percentile(exposure, 99.0, axis=0)
    itm = (cube > 0).mean(axis=0)

    # Always-true invariants at every node: exposure is non-negative and the
    # higher PFE quantile dominates the lower.
    for e, a, b in zip(ee, p95, p99, strict=True):
        assert e >= 0.0
        assert b >= a >= 0.0

    # PFE(95) dominates EE only where the in-the-money probability clears the
    # 95% quantile. Below ~5% ITM the 95th percentile is legitimately 0 while
    # the mean is a small positive number, so this is asserted conditionally.
    for e, a, prob in zip(ee, p95, itm, strict=True):
        if prob > 0.10:
            assert a >= e

    profile = engine.profile_from_cube(cube, grid)
    assert profile.peak_pfe == pytest.approx(max(profile.pfe_95))
    assert profile.peak_pfe >= profile.epe >= 0.0


def test_exposure_is_reproducible() -> None:
    snap = load_market_snapshot()
    ns = _irs_netting_set()
    a = ExposureEngine(ns, snap).run(n_paths=600, seed=99, n_steps=6)
    b = ExposureEngine(ns, snap).run(n_paths=600, seed=99, n_steps=6)
    assert a.ee == b.ee
    assert a.pfe_95 == b.pfe_95
    assert a.peak_pfe == b.peak_pfe


def test_exposure_zero_at_inception_for_near_par_swap() -> None:
    engine = ExposureEngine(_irs_netting_set(), load_market_snapshot())
    grid = engine.build_time_grid(8)
    cube = engine.simulate_cube(grid, n_paths=200, seed=5)
    # t = 0 column is deterministic (no diffusion yet): all paths identical.
    assert cube[:, 0].std() == pytest.approx(0.0, abs=1e-6)


def test_exposure_convergence_across_seeds() -> None:
    snap = load_market_snapshot()
    ns = _irs_netting_set()
    grid = ExposureEngine(ns, snap).build_time_grid(6)
    a = ExposureEngine(ns, snap).simulate_cube(grid, n_paths=4000, seed=1)
    b = ExposureEngine(ns, snap).simulate_cube(grid, n_paths=4000, seed=2)
    ee_a = np.maximum(a, 0.0).mean(axis=0)
    ee_b = np.maximum(b, 0.0).mean(axis=0)
    # Peak-EE estimates from independent seeds agree within Monte Carlo error.
    peak = int(np.argmax(ee_a))
    assert ee_a[peak] == pytest.approx(ee_b[peak], rel=0.08)


def test_mixed_netting_set_runs() -> None:
    engine = ExposureEngine(_mixed_netting_set(), load_market_snapshot())
    profile = engine.run(n_paths=500, seed=7, n_steps=6)
    assert len(profile.ee) == len(profile.time_grid)
    assert profile.peak_pfe > 0.0
    assert np.isfinite(profile.epe)
    # Quote currency matches the trade currency, so nothing is converted.
    assert engine.converted_currencies == ()


def _dated_irs(trade_id: str, currency: str, fixed_rate: float) -> IRS:
    return IRS(
        trade_id=trade_id,
        counterparty_id="CP001",
        notional=5_000_000.0,
        currency=currency,
        trade_date=AS_OF,
        maturity_date=date(2030, 6, 30),
        fixed_rate=fixed_rate,
        direction=SwapDirection.RECEIVE_FIXED,
    )


def test_mixed_currency_irs_converts_at_the_spot() -> None:
    snap = load_market_snapshot()
    usd = _dated_irs("USD1", "USD", 0.02)
    eur = _dated_irs("EUR1", "EUR", 0.01)
    both = ExposureEngine(
        NettingSet("NS", "CP001", (usd, eur)),
        snap,
    )
    only_usd = ExposureEngine(NettingSet("NS", "CP001", (usd,)), snap)
    only_eur = ExposureEngine(NettingSet("NS", "CP001", (eur,)), snap)
    grid = (0.0,)
    total = both.simulate_cube(grid, n_paths=1, seed=1)[0, 0]
    usd_mtm = only_usd.simulate_cube(grid, n_paths=1, seed=1)[0, 0]
    eur_mtm = only_eur.simulate_cube(grid, n_paths=1, seed=1)[0, 0]
    assert both.reporting_currency == "USD"
    assert both.converted_currencies == ("EUR",)
    assert total == pytest.approx(usd_mtm + eur_mtm * snap.fx("EURUSD"))


def test_conversion_uses_the_spot_it_is_given() -> None:
    snap = load_market_snapshot()
    eur = _dated_irs("EUR1", "EUR", 0.01)
    usd = _dated_irs("USD1", "USD", 0.02)
    engine = ExposureEngine(NettingSet("NS", "CP001", (usd, eur)), snap)
    assert engine._to_reporting(10.0, "EUR", {"EURUSD": 2.0}) == pytest.approx(20.0)
    assert engine._to_reporting(10.0, "EUR", {"EURUSD": 4.0}) == pytest.approx(40.0)


def test_inverse_fx_pair_converts_the_same_way() -> None:
    snap = load_market_snapshot()
    direct = snap.fx("EURUSD")
    inverted = replace(snap, fx_spot={"USDEUR": 1.0 / direct})
    eur = _dated_irs("EUR1", "EUR", 0.01)
    usd = _dated_irs("USD1", "USD", 0.02)
    grid = (0.0,)
    via_direct = ExposureEngine(NettingSet("NS", "CP001", (usd, eur)), snap)
    via_inverse = ExposureEngine(NettingSet("NS", "CP001", (usd, eur)), inverted)
    a = via_direct.simulate_cube(grid, n_paths=1, seed=1)[0, 0]
    b = via_inverse.simulate_cube(grid, n_paths=1, seed=1)[0, 0]
    assert a == pytest.approx(b)


def test_mixed_currency_without_fx_raises() -> None:
    snap = replace(load_market_snapshot(), fx_spot={})
    usd = _dated_irs("USD1", "USD", 0.02)
    eur = _dated_irs("EUR1", "EUR", 0.01)
    with pytest.raises(MixedCurrencyError, match="EUR") as exc:
        ExposureEngine(NettingSet("NS", "CP001", (usd, eur)), snap)
    message = str(exc.value)
    assert "USD" in message
    assert "EURUSD" in message


def test_fx_forward_quote_mtm_converts_into_the_trade_currency() -> None:
    snap = load_market_snapshot()
    fx = FXForward(
        trade_id="FX1",
        counterparty_id="CP001",
        notional=1_000_000.0,
        currency="EUR",
        trade_date=AS_OF,
        maturity_date=date(2027, 6, 30),
        base_currency="EUR",
        quote_currency="USD",
        contract_rate=1.20,
        direction=FxDirection.BUY_BASE,
    )
    engine = ExposureEngine(NettingSet("NS", "CP001", (fx,)), snap)
    assert engine.reporting_currency == "EUR"
    assert engine.converted_currencies == ("USD",)
    cube = engine.simulate_cube((0.0,), n_paths=1, seed=1)
    spot = snap.fx("EURUSD")
    usd_mtm = price_fx_forward(
        fx,
        DiscountCurve.from_yield_curve(snap.curve("EUR")),
        DiscountCurve.from_yield_curve(snap.curve("USD")),
        spot,
        AS_OF,
        0.0,
    )
    assert cube[0, 0] == pytest.approx(usd_mtm / spot)


def test_fast_discount_curve_matches_from_zero_rates() -> None:
    engine = ExposureEngine(_irs_netting_set(), load_market_snapshot())
    probes = (0.0, 0.1, 0.25, 1.0, 4.5, 10.0, 30.0)
    for shift in (0.0, 1e-6, -0.002, 0.01, 0.123456789):
        fast = engine._discount_curve("USD", shift)
        slow = DiscountCurve.from_zero_rates(*engine._curve_args("USD", shift))
        for t in probes:
            assert fast.df(t) == slow.df(t)
        assert fast.forward_simple_rate(1.0, 1.5) == slow.forward_simple_rate(1.0, 1.5)


def test_cached_curves_do_not_change_the_cube() -> None:
    engine = ExposureEngine(_irs_netting_set(), load_market_snapshot())
    grid = engine.build_time_grid(3)
    fast = engine.simulate_cube(grid, n_paths=12, seed=4)

    def slow(ccy: str, shift: float) -> DiscountCurve:
        return DiscountCurve.from_zero_rates(*engine._curve_args(ccy, shift))

    engine._discount_curve = slow  # type: ignore[method-assign]
    reference = engine.simulate_cube(grid, n_paths=12, seed=4)
    assert np.array_equal(fast, reference)
