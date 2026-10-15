"""Interest rate swap pricing.

Prices a vanilla fixed-for-floating :class:`~duw.domain.instruments.IRS` in a
single-curve framework: the floating leg is projected off the same discount
curve unless a separate forward curve is supplied. Returns MtM to us (in the
trade currency) given :class:`SwapDirection`.

Each leg runs on a dated schedule (:func:`~duw.pricing.conventions.build_schedule`):
backward from maturity, modified-following on the trade currency's calendar,
accrued with the leg's own day count (fixed 30/360, float ACT/360 by default).
Discounting uses curve time from the market as-of date.

Floating coupons:

- **Future periods** pay the curve forward over the period, sized so that
  ``rate * accrual = DF(start) / DF(end) - 1`` (the projected index accrues on
  the leg's day count, so a par swap still values to zero).
- **The period in progress on the as-of date** fixed in the past. It pays the
  known ``current_fixing`` over the *full* accrual period. Without a fixing
  the coupon is estimated from the curve forward to its end date.
- **Periods that start after the as-of date but before a simulated valuation
  time** fixed on the simulated path. The pricer only sees the curve at the
  valuation time, so it estimates that fixing as the forward from the
  valuation time to the period end. This is a standard exposure-engine
  approximation that a fixings history per path would remove.

The pricer works at inception (``valuation_time == 0``) and along a simulated
path: cashflows paid on or before ``valuation_time`` are dropped, and remaining
cashflows are discounted forward from it. Pure numerics; no Qt.
"""

from __future__ import annotations

from datetime import date

from duw.domain.instruments import IRS, DayCount, Frequency, SwapDirection
from duw.pricing.conventions import (
    build_schedule,
    calendar_for,
    day_count_fraction,
)
from duw.pricing.curves import DiscountCurve, year_fraction


def leg_periods(
    irs: IRS, as_of: date, frequency: Frequency, day_count: DayCount
) -> list[tuple[date, date, float, float, float]]:
    """``(start, end, start_t, end_t, accrual)`` for each period of one leg."""
    schedule = build_schedule(
        irs.trade_date,
        irs.maturity_date,
        frequency.per_year,
        calendar_for(irs.currency),
    )
    return [
        (
            p.start,
            p.end,
            year_fraction(as_of, p.start),
            year_fraction(as_of, p.end),
            day_count_fraction(p.start, p.end, day_count),
        )
        for p in schedule
    ]


def fixed_annuity(
    irs: IRS, discount_curve: DiscountCurve, as_of, valuation_time: float = 0.0
) -> float:
    """Sum of fixed-leg accrual times discount factor, from ``valuation_time``."""
    df_v = discount_curve.df(valuation_time)
    annuity = 0.0
    for _s, _e, _ts, te, accrual in leg_periods(
        irs, as_of, irs.fixed_frequency, irs.fixed_day_count
    ):
        if te <= valuation_time:
            continue
        annuity += accrual * discount_curve.df(te) / df_v
    return annuity


def fixed_leg_pv(
    irs: IRS, discount_curve: DiscountCurve, as_of, valuation_time: float = 0.0
) -> float:
    """PV of the fixed leg per unit notional, discounted from ``valuation_time``."""
    return irs.fixed_rate * fixed_annuity(irs, discount_curve, as_of, valuation_time)


def float_leg_pv(
    irs: IRS,
    discount_curve: DiscountCurve,
    as_of,
    valuation_time: float = 0.0,
    forward_curve: DiscountCurve | None = None,
) -> float:
    """PV of the floating leg per unit notional, discounted from ``valuation_time``."""
    fwd = forward_curve or discount_curve
    df_v = discount_curve.df(valuation_time)
    pv = 0.0
    for start, _e, ts, te, accrual in leg_periods(
        irs, as_of, irs.float_frequency, irs.float_day_count
    ):
        if te <= valuation_time or accrual <= 0.0:
            continue
        if start < as_of:
            # Fixed before the as-of date: the known fixing over the full period.
            if irs.current_fixing is not None:
                index = irs.current_fixing
            else:
                index = fwd.forward_simple_rate(0.0, te) if te > 0.0 else 0.0
        elif ts < valuation_time:
            # Fixed on the simulated path; estimate from the curve at that time.
            index = fwd.forward_simple_rate(valuation_time, te)
        else:
            index = (fwd.df(ts) / fwd.df(te) - 1.0) / accrual
        pv += (index + irs.float_spread) * accrual * discount_curve.df(te) / df_v
    return pv


def par_rate_irs(
    irs: IRS,
    discount_curve: DiscountCurve,
    as_of,
    valuation_time: float = 0.0,
    forward_curve: DiscountCurve | None = None,
) -> float:
    """Fixed rate that makes the swap value to zero at ``valuation_time``."""
    annuity = fixed_annuity(irs, discount_curve, as_of, valuation_time)
    if annuity == 0.0:
        return 0.0
    pv_float = float_leg_pv(irs, discount_curve, as_of, valuation_time, forward_curve)
    return pv_float / annuity


def price_irs(
    irs: IRS,
    discount_curve: DiscountCurve,
    as_of,
    valuation_time: float = 0.0,
    forward_curve: DiscountCurve | None = None,
) -> float:
    """MtM of the swap to us, in the trade currency.

    Positive means the position is an asset to us. For ``PAY_FIXED`` we receive
    float and pay fixed, so MtM is ``PV(float) - PV(fixed)``; ``RECEIVE_FIXED``
    is the negative.
    """
    pv_fixed = fixed_leg_pv(irs, discount_curve, as_of, valuation_time)
    pv_float = float_leg_pv(irs, discount_curve, as_of, valuation_time, forward_curve)
    if irs.direction is SwapDirection.PAY_FIXED:
        mtm_per_unit = pv_float - pv_fixed
    else:
        mtm_per_unit = pv_fixed - pv_float
    return irs.notional * mtm_per_unit
