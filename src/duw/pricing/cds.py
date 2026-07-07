"""Credit default swap pricing.

Prices a single-name :class:`~duw.domain.instruments.CDS` as

    MtM_protection_buyer = notional * (PV_protection - PV_premium)

with the premium leg paid by the protection buyer and the protection leg paid on
default:

- **Protection leg** ``(1 - R) * sum_k DF(u_mid) * (S(u_{k-1}) - S(u_k))`` on a
  fine integration grid, where ``S`` is survival and ``R`` the recovery rate.
- **Premium leg** ``spread * sum_i accrual_i * DF(t_i) * S(t_i)`` on the premium
  schedule, plus a half-period accrual-on-default term.

Survival and discount factors are taken forward from the valuation time, so the
pricer is valid both at inception and along a simulated path. The protection
buyer gains when protection is cheap relative to fair value; the seller's MtM is
the exact negative.

Pure numerics; no Qt.
"""

from __future__ import annotations

from duw.domain.instruments import CDS, CdsDirection
from duw.pricing.curves import (
    DiscountCurve,
    SurvivalCurve,
    period_schedule,
    year_fraction,
)

# Protection-leg integration steps per year.
_PROTECTION_STEPS_PER_YEAR = 12


def protection_leg_pv(
    cds: CDS,
    discount_curve: DiscountCurve,
    survival_curve: SurvivalCurve,
    as_of,
    valuation_time: float = 0.0,
) -> float:
    """PV of the protection leg per unit notional, from ``valuation_time``."""
    start_t = max(year_fraction(as_of, cds.trade_date), valuation_time)
    end_t = year_fraction(as_of, cds.maturity_date)
    if end_t <= start_t:
        return 0.0
    lgd = 1.0 - cds.recovery_rate
    df_v = discount_curve.df(valuation_time)
    s_v = survival_curve.survival(valuation_time)
    if s_v <= 0.0:
        return 0.0
    pv = 0.0
    for sub_start, sub_end in period_schedule(
        start_t, end_t, _PROTECTION_STEPS_PER_YEAR
    ):
        mid = 0.5 * (sub_start + sub_end)
        df_mid = discount_curve.df(mid) / df_v
        marg_pd = (
            survival_curve.survival(sub_start) - survival_curve.survival(sub_end)
        ) / s_v
        pv += lgd * df_mid * marg_pd
    return pv


def premium_leg_pv(
    cds: CDS,
    discount_curve: DiscountCurve,
    survival_curve: SurvivalCurve,
    as_of,
    valuation_time: float = 0.0,
) -> float:
    """PV of the premium leg per unit notional (spread = 1), from ``valuation_time``.

    Returns the risky annuity (the PV of a 1.0 running spread); multiply by the
    contractual ``spread`` for the actual premium PV.
    """
    start_t = year_fraction(as_of, cds.trade_date)
    end_t = year_fraction(as_of, cds.maturity_date)
    df_v = discount_curve.df(valuation_time)
    s_v = survival_curve.survival(valuation_time)
    if s_v <= 0.0:
        return 0.0
    annuity = 0.0
    for accr_start, accr_end in period_schedule(
        start_t, end_t, cds.premium_frequency.per_year
    ):
        if accr_end <= valuation_time:
            continue
        accrual = accr_end - accr_start
        df_end = discount_curve.df(accr_end) / df_v
        surv_end = survival_curve.survival(accr_end) / s_v
        # Premium paid if the name survives to the payment date.
        annuity += accrual * df_end * surv_end
        # Accrual-on-default: roughly half a period accrues on average.
        mid = 0.5 * (max(accr_start, valuation_time) + accr_end)
        df_mid = discount_curve.df(mid) / df_v
        marg_pd = (
            survival_curve.survival(max(accr_start, valuation_time))
            - survival_curve.survival(accr_end)
        ) / s_v
        annuity += 0.5 * accrual * df_mid * marg_pd
    return annuity


def price_cds(
    cds: CDS,
    discount_curve: DiscountCurve,
    survival_curve: SurvivalCurve,
    as_of,
    valuation_time: float = 0.0,
) -> float:
    """MtM of the CDS to us, in the trade currency.

    Positive means the position is an asset to us. For ``BUY_PROTECTION`` the
    MtM is ``notional * (PV_protection - PV_premium)``; ``SELL_PROTECTION`` is
    the negative.
    """
    pv_prot = protection_leg_pv(
        cds, discount_curve, survival_curve, as_of, valuation_time
    )
    risky_annuity = premium_leg_pv(
        cds, discount_curve, survival_curve, as_of, valuation_time
    )
    pv_prem = cds.spread * risky_annuity
    buyer_mtm = cds.notional * (pv_prot - pv_prem)
    if cds.direction is CdsDirection.BUY_PROTECTION:
        return buyer_mtm
    return -buyer_mtm


def par_spread_cds(
    cds: CDS,
    discount_curve: DiscountCurve,
    survival_curve: SurvivalCurve,
    as_of,
    valuation_time: float = 0.0,
) -> float:
    """Fair running spread that makes the CDS value to zero."""
    pv_prot = protection_leg_pv(
        cds, discount_curve, survival_curve, as_of, valuation_time
    )
    risky_annuity = premium_leg_pv(
        cds, discount_curve, survival_curve, as_of, valuation_time
    )
    if risky_annuity == 0.0:
        return 0.0
    return pv_prot / risky_annuity
