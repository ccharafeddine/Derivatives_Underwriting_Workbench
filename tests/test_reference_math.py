"""Pricing and risk math checked against independent references.

QuantLib and py_vollib are dev-only dependencies; each reference test skips if
its library is missing. Invariant tests (CDS par repricing, Monte Carlo
martingale) need nothing extra. These replace the ad-hoc ``verify_math.py``
review script.
"""

from __future__ import annotations

import math
import random
from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pytest

from duw.data.loader import load_market_snapshot
from duw.domain.instruments import (
    CDS,
    IRS,
    CdsDirection,
    DayCount,
    Frequency,
    NettingSet,
    SwapDirection,
)
from duw.pricing.cds import par_spread_cds, standard_cds_maturity
from duw.pricing.conventions import Calendar, build_schedule, day_count_fraction
from duw.pricing.curves import DiscountCurve, SurvivalCurve, year_fraction
from duw.pricing.irs import fixed_leg_pv, float_leg_pv, par_rate_irs, price_irs
from duw.pricing.swaption import _black
from duw.risk.exposure import ExposureEngine
from duw.risk.hull_white import HullWhiteCurve, forward_measure_drift

SNAP = load_market_snapshot()
AS_OF = SNAP.as_of
USD = DiscountCurve.from_yield_curve(SNAP.curve("USD"))


def _ql():
    return pytest.importorskip("QuantLib")


def _qd(ql, d: date):
    return ql.Date(d.day, d.month, d.year)


def _ql_curve(ql, curve: DiscountCurve):
    """A QuantLib curve that reproduces ``curve`` exactly on daily nodes.

    Daily nodes through 12 years make QuantLib's interpolation irrelevant, and
    the ACT/365.25 day counter matches the app's curve-time axis.
    """
    dates = [AS_OF + timedelta(days=k) for k in range(0, 12 * 366)]
    dfs = [curve.df(year_fraction(AS_OF, d)) for d in dates]
    out = ql.DiscountCurve([_qd(ql, d) for d in dates], dfs, ql.Actual36525())
    out.enableExtrapolation()
    return ql.YieldTermStructureHandle(out)


# --------------------------------------------------------------------------- #
# Day counts, calendars and schedules
# --------------------------------------------------------------------------- #
def test_day_counts_match_quantlib() -> None:
    ql = _ql()
    refs = {
        DayCount.ACT_360: ql.Actual360(),
        DayCount.ACT_365: ql.Actual365Fixed(),
        DayCount.THIRTY_360: ql.Thirty360(ql.Thirty360.BondBasis),
    }
    rng = random.Random(3)
    for _ in range(400):
        d1 = date(2020, 1, 1) + timedelta(days=rng.randrange(0, 4000))
        d2 = d1 + timedelta(days=rng.randrange(1, 4000))
        for dc, ref in refs.items():
            expected = ref.yearFraction(_qd(ql, d1), _qd(ql, d2))
            assert day_count_fraction(d1, d2, dc) == pytest.approx(expected, abs=1e-14)
    # The month-end cases that distinguish 30/360 variants.
    for d1, d2 in [
        (date(2025, 1, 31), date(2025, 3, 31)),
        (date(2025, 2, 28), date(2025, 8, 31)),
        (date(2024, 2, 29), date(2025, 2, 28)),
    ]:
        expected = refs[DayCount.THIRTY_360].yearFraction(_qd(ql, d1), _qd(ql, d2))
        assert day_count_fraction(d1, d2, DayCount.THIRTY_360) == pytest.approx(
            expected
        )


@pytest.mark.parametrize(
    ("name", "factory"),
    [
        ("USNY", lambda ql: ql.UnitedStates(ql.UnitedStates.FederalReserve)),
        ("TARGET", lambda ql: ql.TARGET()),
        ("LONDON", lambda ql: ql.UnitedKingdom(ql.UnitedKingdom.Settlement)),
    ],
)
def test_calendars_match_quantlib(name, factory) -> None:
    ql = _ql()
    ref = factory(ql)
    ours = Calendar(name)
    d = date(2024, 1, 1)
    while d < date(2036, 1, 1):
        assert ours.is_business_day(d) == ref.isBusinessDay(_qd(ql, d)), d
        d += timedelta(days=1)


@pytest.mark.parametrize(
    ("start", "end", "per_year"),
    [
        (date(2025, 6, 30), date(2030, 6, 30), 4),
        (date(2024, 3, 31), date(2029, 3, 31), 1),
        (date(2025, 7, 15), date(2032, 1, 31), 2),
        (date(2025, 6, 30), date(2035, 6, 30), 12),
    ],
)
def test_schedules_match_quantlib(start, end, per_year) -> None:
    ql = _ql()
    ref = ql.Schedule(
        _qd(ql, start),
        _qd(ql, end),
        ql.Period(12 // per_year, ql.Months),
        ql.UnitedStates(ql.UnitedStates.FederalReserve),
        ql.ModifiedFollowing,
        ql.ModifiedFollowing,
        ql.DateGeneration.Backward,
        False,
    )
    ref_dates = [date(x.year(), x.month(), x.dayOfMonth()) for x in ref]
    ours = build_schedule(start, end, per_year, Calendar("USNY"))
    assert [ours[0].start] + [p.end for p in ours] == ref_dates


# --------------------------------------------------------------------------- #
# Interest rate swaps (fresh and seasoned) vs QuantLib
# --------------------------------------------------------------------------- #
def _ql_swap_npv(ql, irs: IRS, fixing_dates_rates=()) -> tuple[float, float]:
    """(fixed leg NPV, float leg NPV) per unit notional from QuantLib."""
    ql.Settings.instance().evaluationDate = _qd(ql, AS_OF)
    ql.IborCoupon.createAtParCoupons()
    handle = _ql_curve(ql, USD)
    cal = ql.UnitedStates(ql.UnitedStates.FederalReserve)
    dcs = {
        DayCount.ACT_360: ql.Actual360(),
        DayCount.ACT_365: ql.Actual365Fixed(),
        DayCount.THIRTY_360: ql.Thirty360(ql.Thirty360.BondBasis),
    }

    def sched(freq: Frequency):
        return ql.Schedule(
            _qd(ql, irs.trade_date),
            _qd(ql, irs.maturity_date),
            ql.Period(12 // freq.per_year, ql.Months),
            cal,
            ql.ModifiedFollowing,
            ql.ModifiedFollowing,
            ql.DateGeneration.Backward,
            False,
        )

    index = ql.IborIndex(
        "TEST3M",
        ql.Period(12 // irs.float_frequency.per_year, ql.Months),
        0,
        ql.USDCurrency(),
        cal,
        ql.ModifiedFollowing,
        False,
        dcs[irs.float_day_count],
        handle,
    )
    index.clearFixings()
    for d, r in fixing_dates_rates:
        index.addFixing(_qd(ql, d), r)
    swap = ql.VanillaSwap(
        ql.Swap.Payer,
        1.0,
        sched(irs.fixed_frequency),
        irs.fixed_rate,
        dcs[irs.fixed_day_count],
        sched(irs.float_frequency),
        index,
        irs.float_spread,
        dcs[irs.float_day_count],
    )
    swap.setPricingEngine(ql.DiscountingSwapEngine(handle))
    return -swap.fixedLegNPV(), swap.floatingLegNPV()


@pytest.mark.parametrize(
    ("fixed_dc", "float_dc"),
    [
        (DayCount.THIRTY_360, DayCount.ACT_360),
        (DayCount.ACT_365, DayCount.ACT_365),
        (DayCount.ACT_360, DayCount.ACT_360),
    ],
)
def test_fresh_irs_legs_match_quantlib(fixed_dc, float_dc) -> None:
    ql = _ql()
    irs = IRS(
        trade_id="Q",
        counterparty_id="C",
        notional=1.0,
        currency="USD",
        trade_date=AS_OF,
        maturity_date=date(2032, 6, 30),
        fixed_rate=0.043,
        direction=SwapDirection.PAY_FIXED,
        fixed_day_count=fixed_dc,
        float_day_count=float_dc,
        float_spread=0.0015,
    )
    ref_fixed, ref_float = _ql_swap_npv(ql, irs)
    assert fixed_leg_pv(irs, USD, AS_OF) == pytest.approx(ref_fixed, abs=1e-10)
    assert float_leg_pv(irs, USD, AS_OF) == pytest.approx(ref_float, abs=1e-10)


def test_seasoned_irs_uses_known_fixing_over_full_accrual() -> None:
    ql = _ql()
    irs = IRS(
        trade_id="S",
        counterparty_id="C",
        notional=1.0,
        currency="USD",
        trade_date=date(2024, 4, 1),
        maturity_date=date(2029, 4, 2),
        fixed_rate=0.043,
        direction=SwapDirection.PAY_FIXED,
        current_fixing=0.0525,
    )
    periods = build_schedule(irs.trade_date, irs.maturity_date, 4, Calendar("USNY"))
    current = next(p for p in periods if p.start < AS_OF < p.end)
    ref_fixed, ref_float = _ql_swap_npv(ql, irs, [(current.start, 0.0525)])
    assert fixed_leg_pv(irs, USD, AS_OF) == pytest.approx(ref_fixed, abs=1e-10)
    assert float_leg_pv(irs, USD, AS_OF) == pytest.approx(ref_float, abs=1e-10)
    # The known coupon is paid over the whole period, not projected from today.
    accrual = day_count_fraction(current.start, current.end, DayCount.ACT_360)
    unfixed = replace(irs, current_fixing=None)
    delta = float_leg_pv(irs, USD, AS_OF) - float_leg_pv(unfixed, USD, AS_OF)
    est = USD.forward_simple_rate(0.0, year_fraction(AS_OF, current.end))
    expected = (0.0525 - est) * accrual * USD.df(year_fraction(AS_OF, current.end))
    assert delta == pytest.approx(expected, rel=1e-12)


def test_par_swap_prices_to_zero_with_real_day_counts() -> None:
    irs = IRS(
        trade_id="P",
        counterparty_id="C",
        notional=1e8,
        currency="USD",
        trade_date=AS_OF,
        maturity_date=date(2035, 6, 29),
        fixed_rate=0.0,
        direction=SwapDirection.PAY_FIXED,
    )
    irs = replace(irs, fixed_rate=par_rate_irs(irs, USD, AS_OF))
    assert price_irs(irs, USD, AS_OF) == pytest.approx(0.0, abs=1e-6)


# --------------------------------------------------------------------------- #
# Swaption Black formula vs py_vollib
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("f", "k", "vol", "t"),
    [(0.042, 0.045, 0.20, 2.0), (0.03, 0.025, 0.35, 5.0), (0.04, 0.04, 0.15, 0.5)],
)
def test_black_matches_py_vollib(f, k, vol, t) -> None:
    black = pytest.importorskip("py_vollib.black").black
    assert _black(f, k, vol, t, True) == pytest.approx(
        black("c", f, k, t, 0.0, vol), abs=1e-15
    )
    assert _black(f, k, vol, t, False) == pytest.approx(
        black("p", f, k, t, 0.0, vol), abs=1e-15
    )


# --------------------------------------------------------------------------- #
# CDS bootstrap: par repricing and QuantLib survival
# --------------------------------------------------------------------------- #
def _cds(issuer: str, maturity: date, spread: float, recovery: float) -> CDS:
    return CDS(
        trade_id="B",
        counterparty_id="C",
        notional=1.0,
        currency="USD",
        trade_date=AS_OF,
        maturity_date=maturity,
        reference_entity=issuer,
        direction=CdsDirection.BUY_PROTECTION,
        spread=spread,
        recovery_rate=recovery,
    )


@pytest.mark.parametrize("issuer", sorted(SNAP.credit_curves))
def test_cds_bootstrap_reprices_every_quote(issuer) -> None:
    cc = SNAP.credit(issuer)
    curve = SurvivalCurve.bootstrap(cc, discount_curve=USD, as_of=AS_OF)
    for tenor, quote in zip(cc.tenors, cc.spreads, strict=True):
        cds = _cds(issuer, standard_cds_maturity(AS_OF, tenor), quote, cc.recovery_rate)
        par = par_spread_cds(cds, USD, curve, AS_OF)
        assert abs(par - quote) * 1e4 < 0.1, (issuer, tenor)


@pytest.mark.parametrize("issuer", sorted(SNAP.credit_curves))
def test_cds_survival_matches_quantlib(issuer) -> None:
    ql = _ql()
    ql.Settings.instance().evaluationDate = _qd(ql, AS_OF)
    cc = SNAP.credit(issuer)
    handle = _ql_curve(ql, USD)
    cal = ql.UnitedStates(ql.UnitedStates.FederalReserve)
    helpers = [
        ql.SpreadCdsHelper(
            ql.QuoteHandle(ql.SimpleQuote(s)),
            ql.Period(int(round(t * 12)), ql.Months),
            0,
            cal,
            ql.Quarterly,
            ql.ModifiedFollowing,
            ql.DateGeneration.Backward,
            ql.Actual360(),
            cc.recovery_rate,
            handle,
        )
        for t, s in zip(cc.tenors, cc.spreads, strict=True)
    ]
    ref = ql.PiecewiseFlatHazardRate(_qd(ql, AS_OF), helpers, ql.Actual36525())
    ref.enableExtrapolation()
    ours = SurvivalCurve.bootstrap(cc, discount_curve=USD, as_of=AS_OF)
    for tenor in cc.tenors:
        d = standard_cds_maturity(AS_OF, tenor)
        expected = ref.survivalProbability(_qd(ql, d))
        assert ours.survival(year_fraction(AS_OF, d)) == pytest.approx(
            expected, abs=5e-4
        )


# --------------------------------------------------------------------------- #
# Hull-White curves and Monte Carlo martingale invariants
# --------------------------------------------------------------------------- #
def test_hull_white_curve_is_today_at_inception_and_forward_unbiased() -> None:
    kappa, sigma = 0.10, 0.0105
    hw0 = HullWhiteCurve(USD, 0.0, 0.0, kappa, sigma)
    for u in (0.5, 2.0, 7.0):
        assert hw0.df(u) == pytest.approx(USD.df(u), rel=1e-14)
    # E^t[P(t,T)] = P0(T) / P0(t) when x(t) ~ N(-M(t), var(t)) (Gauss-Hermite).
    nodes, weights = np.polynomial.hermite_e.hermegauss(40)
    for t in (1.0, 3.0, 6.0):
        sd = sigma * math.sqrt((1.0 - math.exp(-2.0 * kappa * t)) / (2.0 * kappa))
        mean = -forward_measure_drift(t, kappa, sigma)
        for big_t in (t + 0.25, t + 5.0):
            vals = [
                HullWhiteCurve(USD, t, mean + sd * z, kappa, sigma).df(big_t)
                / HullWhiteCurve(USD, t, mean + sd * z, kappa, sigma).df(t)
                for z in nodes
            ]
            expected = USD.df(big_t) / USD.df(t)
            got = float(np.dot(weights, vals) / weights.sum())
            assert got == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize("direction", list(SwapDirection))
def test_exposure_is_martingale_consistent_for_par_swaps(direction) -> None:
    """Mean discounted simulated MtM equals the forward value of the trade.

    ``P0(t) E[V(t)]`` must equal today's PV of the cashflows still to come after
    ``t`` (zero only at inception for a par swap). Checked within 4 Monte Carlo
    standard errors at every grid date.
    """
    irs = IRS(
        trade_id="M",
        counterparty_id="C",
        notional=1e8,
        currency="USD",
        trade_date=AS_OF,
        maturity_date=date(2035, 6, 29),
        fixed_rate=0.0,
        direction=direction,
    )
    irs = replace(irs, fixed_rate=par_rate_irs(irs, USD, AS_OF))
    engine = ExposureEngine(NettingSet("N", "C", (irs,)), SNAP)
    grid = (0.0, 1.0, 2.5, 4.0, 6.0, 8.5)
    n = 2000
    cube = engine.simulate_cube(grid, n_paths=n, seed=11)
    for k, t in enumerate(grid):
        df = USD.df(t)
        expected = price_irs(irs, USD, AS_OF, t) * df
        mean = cube[:, k].mean() * df
        se = cube[:, k].std() * df / math.sqrt(n)
        assert abs(mean - expected) <= 4.0 * se + 1.0, (t, mean, expected, se)
