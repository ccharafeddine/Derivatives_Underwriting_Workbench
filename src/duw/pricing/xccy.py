"""Cross-currency swap pricing.

Prices a fixed-for-fixed :class:`~duw.domain.instruments.CrossCurrencySwap`. Each
leg is a fixed-coupon stream in its own currency, discounted on that currency's
curve, plus a principal exchange at maturity when ``exchange_notional``. The
foreign leg PV is converted to the base currency at the prevailing spot, so the
reported MtM (in the base currency) moves with both rate curves and the FX rate:

    MtM_base = +/-( PV_base_leg - fx_base_per_foreign * PV_foreign_leg )

with the sign set by :class:`CrossCurrencyDirection`. Leg PVs are discounted to
``valuation_time`` (like the other pricers), so the pricer works at inception and
along a simulated path.

Pure numerics; no Qt.
"""

from __future__ import annotations

from duw.domain.instruments import CrossCurrencyDirection, CrossCurrencySwap
from duw.pricing.curves import DiscountCurve, period_schedule, year_fraction


def _fixed_leg_pv(
    notional: float,
    rate: float,
    curve: DiscountCurve,
    start_t: float,
    end_t: float,
    per_year: int,
    valuation_time: float,
    exchange_notional: bool,
) -> float:
    """PV of a fixed-coupon leg (+ principal at maturity), in the leg currency."""
    df_v = curve.df(valuation_time)
    pv = 0.0
    for accr_start, accr_end in period_schedule(start_t, end_t, per_year):
        if accr_end <= valuation_time:
            continue
        pv += rate * (accr_end - accr_start) * curve.df(accr_end) / df_v
    if exchange_notional and end_t > valuation_time:
        pv += curve.df(end_t) / df_v
    return notional * pv


def price_cross_currency_swap(
    swap: CrossCurrencySwap,
    base_curve: DiscountCurve,
    foreign_curve: DiscountCurve,
    fx_base_per_foreign: float,
    as_of,
    valuation_time: float = 0.0,
) -> float:
    """MtM of the cross-currency swap to us, in the base currency.

    ``fx_base_per_foreign`` is the number of base-currency units per one
    foreign-currency unit at ``valuation_time``.
    """
    start_t = year_fraction(as_of, swap.trade_date)
    end_t = year_fraction(as_of, swap.maturity_date)
    per_year = swap.frequency.per_year
    pv_base = _fixed_leg_pv(
        swap.notional,
        swap.base_rate,
        base_curve,
        start_t,
        end_t,
        per_year,
        valuation_time,
        swap.exchange_notional,
    )
    pv_foreign = _fixed_leg_pv(
        swap.foreign_notional,
        swap.foreign_rate,
        foreign_curve,
        start_t,
        end_t,
        per_year,
        valuation_time,
        swap.exchange_notional,
    )
    pv_foreign_in_base = pv_foreign * fx_base_per_foreign
    if swap.direction is CrossCurrencyDirection.RECEIVE_BASE:
        return pv_base - pv_foreign_in_base
    return pv_foreign_in_base - pv_base
