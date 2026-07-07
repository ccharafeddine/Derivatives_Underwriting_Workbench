"""Interest rate swap pricing.

Prices a vanilla fixed-for-floating :class:`~duw.domain.instruments.IRS` in a
single-curve framework: the floating leg is projected with simple forward rates
off the same discount curve unless a separate forward curve is supplied. Returns
MtM to us (in the trade currency) given :class:`SwapDirection`.

The pricer works at inception (``valuation_time == 0``) and at a future
valuation time along a simulated path: cashflows on or before ``valuation_time``
are dropped and remaining cashflows are discounted forward from it. Accruals use
the equal-period year fractions from :func:`period_schedule` (a v1 day-count
simplification), which makes a par swap value to exactly zero at inception.

Pure numerics; no Qt.
"""

from __future__ import annotations

from duw.domain.instruments import IRS, SwapDirection
from duw.pricing.curves import DiscountCurve, period_schedule, year_fraction


def _leg_times(
    irs: IRS, discount_curve: DiscountCurve, as_of, per_year: int
) -> list[tuple[float, float]]:
    start_t = year_fraction(as_of, irs.trade_date)
    end_t = year_fraction(as_of, irs.maturity_date)
    return period_schedule(start_t, end_t, per_year)


def fixed_leg_pv(
    irs: IRS, discount_curve: DiscountCurve, as_of, valuation_time: float = 0.0
) -> float:
    """PV of the fixed leg per unit notional, discounted from ``valuation_time``."""
    df_v = discount_curve.df(valuation_time)
    pv = 0.0
    for accr_start, accr_end in _leg_times(
        irs, discount_curve, as_of, irs.fixed_frequency.per_year
    ):
        if accr_end <= valuation_time:
            continue
        accrual = accr_end - accr_start
        pv += irs.fixed_rate * accrual * discount_curve.df(accr_end) / df_v
    return pv


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
    for accr_start, accr_end in _leg_times(
        irs, discount_curve, as_of, irs.float_frequency.per_year
    ):
        if accr_end <= valuation_time:
            continue
        accrual = accr_end - accr_start
        # Project the floating fixing as a simple forward over the accrual period.
        proj_start = max(accr_start, valuation_time)
        forward = fwd.forward_simple_rate(proj_start, accr_end)
        rate = forward + irs.float_spread
        pv += rate * accrual * discount_curve.df(accr_end) / df_v
    return pv


def par_rate_irs(
    irs: IRS,
    discount_curve: DiscountCurve,
    as_of,
    valuation_time: float = 0.0,
    forward_curve: DiscountCurve | None = None,
) -> float:
    """Fixed rate that makes the swap value to zero at ``valuation_time``."""
    df_v = discount_curve.df(valuation_time)
    annuity = 0.0
    for accr_start, accr_end in _leg_times(
        irs, discount_curve, as_of, irs.fixed_frequency.per_year
    ):
        if accr_end <= valuation_time:
            continue
        accrual = accr_end - accr_start
        annuity += accrual * discount_curve.df(accr_end) / df_v
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
