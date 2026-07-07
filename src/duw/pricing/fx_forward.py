"""FX forward pricing.

Prices an :class:`~duw.domain.instruments.FXForward` by covered interest parity.
The prevailing forward from the valuation time ``t_v`` to maturity ``T`` is

    F(t_v, T) = spot * DF_base(t_v, T) / DF_quote(t_v, T)

and the MtM (in the **quote** currency) of a position to buy the base currency
at the contracted rate ``K`` is the discounted difference between the prevailing
forward and ``K``, scaled by notional (which is in the base currency):

    MtM_buy_base  = notional * (F - K) * DF_quote(t_v, T)
    MtM_sell_base = notional * (K - F) * DF_quote(t_v, T)

``spot`` and ``contract_rate`` are quoted as units of quote currency per unit of
base currency (e.g. USD per EUR for ``EURUSD``). The result is in the quote
currency; a reporting-currency conversion, if needed, happens upstream.

Pure numerics; no Qt.
"""

from __future__ import annotations

from duw.domain.instruments import FxDirection, FXForward
from duw.pricing.curves import DiscountCurve, year_fraction


def forward_rate_fx(
    spot: float,
    base_curve: DiscountCurve,
    quote_curve: DiscountCurve,
    maturity_time: float,
    valuation_time: float = 0.0,
) -> float:
    """Prevailing CIP forward from ``valuation_time`` to ``maturity_time``."""
    df_base = base_curve.forward_df(valuation_time, maturity_time)
    df_quote = quote_curve.forward_df(valuation_time, maturity_time)
    return spot * df_base / df_quote


def price_fx_forward(
    fx: FXForward,
    base_curve: DiscountCurve,
    quote_curve: DiscountCurve,
    spot: float,
    as_of,
    valuation_time: float = 0.0,
) -> float:
    """MtM of the FX forward to us, in the quote currency.

    ``base_curve`` and ``quote_curve`` discount in the base and quote
    currencies respectively; ``spot`` is the current base/quote FX rate.
    """
    maturity_time = year_fraction(as_of, fx.maturity_date)
    if maturity_time <= valuation_time:
        return 0.0
    forward = forward_rate_fx(
        spot, base_curve, quote_curve, maturity_time, valuation_time
    )
    df_quote = quote_curve.forward_df(valuation_time, maturity_time)
    if fx.direction is FxDirection.BUY_BASE:
        diff = forward - fx.contract_rate
    else:
        diff = fx.contract_rate - forward
    return fx.notional * diff * df_quote
