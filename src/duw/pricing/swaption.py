"""European swaption pricing (Black on the forward swap rate).

Prices a cash-settled :class:`~duw.domain.instruments.Swaption` as an option on
the fixed rate of the forward-starting underlying swap. The underlying starts at
the option expiry and runs ``underlying_tenor_years``; its forward swap rate and
annuity come off the (single) discount curve. A payer swaption is a call on the
swap rate, a receiver a put.

    value = notional * annuity * Black(forward, strike, vol, T_expiry)

The annuity is discounted to ``valuation_time`` (like the other pricers), so the
returned MtM is expressed at ``valuation_time`` and the pricer works both at
inception and along a simulated path. Beyond expiry the option has settled and
the MtM is 0. Black uses a lognormal swap-rate vol; falling back to intrinsic
when the rate, strike, vol, or time is non-positive.

Pure numerics; no Qt.
"""

from __future__ import annotations

from math import erf, log, sqrt

from duw.domain.instruments import Swaption, SwaptionDirection
from duw.pricing.curves import DiscountCurve, period_schedule, year_fraction


def _phi(x: float) -> float:
    """Standard-normal CDF via the error function (no scipy in the hot loop)."""
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _black(
    forward: float, strike: float, vol: float, expiry: float, is_call: bool
) -> float:
    """Black formula per unit annuity; intrinsic when inputs are degenerate."""
    if expiry <= 0.0 or vol <= 0.0 or forward <= 0.0 or strike <= 0.0:
        return max(forward - strike, 0.0) if is_call else max(strike - forward, 0.0)
    v = vol * sqrt(expiry)
    d1 = (log(forward / strike) + 0.5 * v * v) / v
    d2 = d1 - v
    if is_call:
        return forward * _phi(d1) - strike * _phi(d2)
    return strike * _phi(-d2) - forward * _phi(-d1)


def forward_swap_rate_and_annuity(
    curve: DiscountCurve,
    expiry_t: float,
    tenor: float,
    per_year: int,
    valuation_time: float = 0.0,
) -> tuple[float, float]:
    """Return ``(forward swap rate, annuity)`` for the forward-starting swap.

    The annuity (PV of a unit fixed coupon stream) is discounted to
    ``valuation_time``.
    """
    df_v = curve.df(valuation_time)
    annuity = 0.0
    for accr_start, accr_end in period_schedule(expiry_t, expiry_t + tenor, per_year):
        annuity += (accr_end - accr_start) * curve.df(accr_end) / df_v
    if annuity <= 0.0:
        return 0.0, 0.0
    forward = (curve.df(expiry_t) / df_v - curve.df(expiry_t + tenor) / df_v) / annuity
    return forward, annuity


def price_swaption(
    swaption: Swaption,
    discount_curve: DiscountCurve,
    as_of,
    valuation_time: float = 0.0,
) -> float:
    """MtM of the swaption to us, in the trade currency."""
    expiry_t = year_fraction(as_of, swaption.maturity_date)
    if valuation_time > expiry_t:
        return 0.0  # cash-settled and expired
    forward, annuity = forward_swap_rate_and_annuity(
        discount_curve,
        expiry_t,
        swaption.underlying_tenor_years,
        swaption.underlying_frequency.per_year,
        valuation_time,
    )
    is_call = swaption.direction is SwaptionDirection.PAYER
    black_value = _black(
        forward,
        swaption.strike,
        swaption.volatility,
        expiry_t - valuation_time,
        is_call,
    )
    value = swaption.notional * annuity * black_value
    return value if swaption.bought else -value
