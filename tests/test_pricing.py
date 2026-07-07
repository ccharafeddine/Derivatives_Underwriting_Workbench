"""Pricing tests (Session 2): curves and the three pricers."""

from __future__ import annotations

from datetime import date
from math import exp

import pytest

from duw.data.loader import load_market_snapshot
from duw.domain.instruments import (
    CDS,
    IRS,
    CdsDirection,
    Frequency,
    FxDirection,
    FXForward,
    SwapDirection,
)
from duw.domain.market import CreditCurve, YieldCurve
from duw.pricing.cds import par_spread_cds, price_cds
from duw.pricing.curves import DiscountCurve, SurvivalCurve, year_fraction
from duw.pricing.fx_forward import forward_rate_fx, price_fx_forward
from duw.pricing.irs import par_rate_irs, price_irs

AS_OF = date(2025, 6, 30)


# --------------------------------------------------------------------------- #
# Discount curve
# --------------------------------------------------------------------------- #
def _usd_curve() -> DiscountCurve:
    snap = load_market_snapshot()
    return DiscountCurve.from_yield_curve(snap.curve("USD"))


def test_df_at_zero_is_one() -> None:
    curve = _usd_curve()
    assert curve.df(0.0) == 1.0


def test_discount_factors_monotone_decreasing() -> None:
    curve = _usd_curve()
    grid = [0.1, 0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 15.0]
    dfs = [curve.df(t) for t in grid]
    assert all(later < earlier for earlier, later in zip(dfs, dfs[1:], strict=False))
    assert all(0.0 < d <= 1.0 for d in dfs)


def test_forward_df_consistency() -> None:
    curve = _usd_curve()
    # df(t2) == df(t1) * forward_df(t1, t2)
    assert curve.df(5.0) == pytest.approx(curve.df(2.0) * curve.forward_df(2.0, 5.0))


def test_zero_rate_roundtrip() -> None:
    curve = DiscountCurve.from_zero_rates((1.0, 5.0), (0.04, 0.045))
    # Node zero rates recovered exactly.
    assert curve.zero_rate(1.0) == pytest.approx(0.04)
    assert curve.zero_rate(5.0) == pytest.approx(0.045)


# --------------------------------------------------------------------------- #
# IRS
# --------------------------------------------------------------------------- #
def _base_irs(fixed_rate: float, direction: SwapDirection) -> IRS:
    return IRS(
        trade_id="IRS1",
        counterparty_id="CP001",
        notional=10_000_000.0,
        currency="USD",
        trade_date=AS_OF,
        maturity_date=date(2030, 6, 30),
        fixed_rate=fixed_rate,
        direction=direction,
        fixed_frequency=Frequency.ANNUAL,
        float_frequency=Frequency.QUARTERLY,
    )


def test_par_swap_is_approximately_zero() -> None:
    curve = _usd_curve()
    probe = _base_irs(0.0, SwapDirection.PAY_FIXED)
    par = par_rate_irs(probe, curve, AS_OF)
    at_par = _base_irs(par, SwapDirection.PAY_FIXED)
    mtm = price_irs(at_par, curve, AS_OF)
    # A par swap values to zero relative to notional.
    assert abs(mtm) < 1.0  # < $1 on a $10mm swap
    assert 0.02 < par < 0.08  # sane USD par rate


def test_irs_direction_sign_and_symmetry() -> None:
    curve = _usd_curve()
    par = par_rate_irs(_base_irs(0.0, SwapDirection.PAY_FIXED), curve, AS_OF)
    # Below-par fixed rate: paying fixed is cheap -> asset to the payer.
    low = par - 0.01
    pay = price_irs(_base_irs(low, SwapDirection.PAY_FIXED), curve, AS_OF)
    receive = price_irs(_base_irs(low, SwapDirection.RECEIVE_FIXED), curve, AS_OF)
    assert pay > 0
    assert receive == pytest.approx(-pay)


def test_irs_priceable_at_future_time() -> None:
    curve = _usd_curve()
    irs = _base_irs(0.045, SwapDirection.PAY_FIXED)
    mtm_future = price_irs(irs, curve, AS_OF, valuation_time=2.0)
    assert isinstance(mtm_future, float)


# --------------------------------------------------------------------------- #
# FX forward
# --------------------------------------------------------------------------- #
def _fx(contract_rate: float, direction: FxDirection) -> FXForward:
    return FXForward(
        trade_id="FX1",
        counterparty_id="CP001",
        notional=10_000_000.0,
        currency="EUR",
        trade_date=AS_OF,
        maturity_date=date(2026, 6, 30),
        base_currency="EUR",
        quote_currency="USD",
        contract_rate=contract_rate,
        direction=direction,
    )


def test_fx_forward_struck_at_market_is_zero() -> None:
    snap = load_market_snapshot()
    base = DiscountCurve.from_yield_curve(snap.curve("EUR"))
    quote = DiscountCurve.from_yield_curve(snap.curve("USD"))
    spot = snap.fx("EURUSD")
    maturity_t = year_fraction(AS_OF, date(2026, 6, 30))
    fair = forward_rate_fx(spot, base, quote, maturity_t)
    fx = _fx(fair, FxDirection.BUY_BASE)
    mtm = price_fx_forward(fx, base, quote, spot, AS_OF)
    assert abs(mtm) < 1e-3  # struck at the market forward -> ~0


def test_fx_forward_direction_symmetry() -> None:
    snap = load_market_snapshot()
    base = DiscountCurve.from_yield_curve(snap.curve("EUR"))
    quote = DiscountCurve.from_yield_curve(snap.curve("USD"))
    spot = snap.fx("EURUSD")
    buy = price_fx_forward(_fx(1.05, FxDirection.BUY_BASE), base, quote, spot, AS_OF)
    sell = price_fx_forward(_fx(1.05, FxDirection.SELL_BASE), base, quote, spot, AS_OF)
    assert buy == pytest.approx(-sell)
    # Contracted below the prevailing forward -> buying base is an asset.
    assert buy > 0


# --------------------------------------------------------------------------- #
# CDS
# --------------------------------------------------------------------------- #
def _survival() -> SurvivalCurve:
    snap = load_market_snapshot()
    return SurvivalCurve.bootstrap(snap.credit("ACME"))


def _cds(spread: float, direction: CdsDirection) -> CDS:
    return CDS(
        trade_id="CDS1",
        counterparty_id="CP001",
        notional=10_000_000.0,
        currency="USD",
        trade_date=AS_OF,
        maturity_date=date(2030, 6, 30),
        reference_entity="ACME",
        direction=direction,
        spread=spread,
        recovery_rate=0.4,
    )


def test_survival_curve_monotone_and_bounded() -> None:
    surv = _survival()
    grid = [0.0, 0.5, 1.0, 2.0, 5.0, 10.0]
    s = [surv.survival(t) for t in grid]
    assert s[0] == pytest.approx(1.0)
    assert all(later <= earlier for earlier, later in zip(s, s[1:], strict=False))
    assert all(0.0 <= v <= 1.0 for v in s)


def test_cds_buyer_seller_are_opposite() -> None:
    curve = _usd_curve()
    surv = _survival()
    buy = price_cds(_cds(0.005, CdsDirection.BUY_PROTECTION), curve, surv, AS_OF)
    sell = price_cds(_cds(0.005, CdsDirection.SELL_PROTECTION), curve, surv, AS_OF)
    assert buy == pytest.approx(-sell)


def test_cds_cheap_protection_is_asset_to_buyer() -> None:
    curve = _usd_curve()
    surv = _survival()
    par = par_spread_cds(_cds(0.0, CdsDirection.BUY_PROTECTION), curve, surv, AS_OF)
    # Buying protection well below par is an asset to the buyer.
    cheap_buy = price_cds(
        _cds(par - 0.004, CdsDirection.BUY_PROTECTION), curve, surv, AS_OF
    )
    assert cheap_buy > 0
    # Buyer MtM decreases as the contractual spread rises.
    dear_buy = price_cds(
        _cds(par + 0.004, CdsDirection.BUY_PROTECTION), curve, surv, AS_OF
    )
    assert dear_buy < cheap_buy


def test_cds_at_par_is_approximately_zero() -> None:
    curve = _usd_curve()
    surv = _survival()
    par = par_spread_cds(_cds(0.0, CdsDirection.BUY_PROTECTION), curve, surv, AS_OF)
    mtm = price_cds(_cds(par, CdsDirection.BUY_PROTECTION), curve, surv, AS_OF)
    assert abs(mtm) < 0.01 * 10_000_000.0  # within 1% of notional of zero


def test_par_spread_is_reasonable() -> None:
    curve = _usd_curve()
    surv = _survival()
    par = par_spread_cds(_cds(0.0, CdsDirection.BUY_PROTECTION), curve, surv, AS_OF)
    # ACME 5y spread is ~148 bps; par should be in the same neighborhood.
    assert 0.008 < par < 0.025


def test_credit_curve_construction() -> None:
    cc = CreditCurve(issuer="X", tenors=(1.0, 5.0), spreads=(0.01, 0.02))
    surv = SurvivalCurve.bootstrap(cc)
    assert surv.survival(5.0) < surv.survival(1.0)
    yc = YieldCurve(currency="USD", tenors=(1.0,), zero_rates=(0.04,))
    assert DiscountCurve.from_yield_curve(yc).df(1.0) == pytest.approx(exp(-0.04))
