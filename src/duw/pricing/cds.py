"""Credit default swap pricing.

Prices a single-name :class:`~duw.domain.instruments.CDS` as

    MtM_protection_buyer = notional * (PV_protection - PV_premium)

with the premium leg paid by the protection buyer and the protection leg paid on
default:

- **Protection leg** ``(1 - R) * sum_k DF(u_mid) * (S(u_{k-1}) - S(u_k))`` on a
  fine integration grid, where ``S`` is survival and ``R`` the recovery rate.
- **Premium leg** ``spread * sum_i accrual_i * DF(t_i) * S(t_i)`` on a dated
  premium schedule (business-day adjusted on the trade currency's calendar,
  accrued with the trade's day count, ACT/360 by default), plus
  accrual-on-default: a default in a period pays the premium accrued from the
  period start to the default time, approximated at the midpoint of the
  still-live part of the period.

Survival and discount factors are taken forward from the valuation time, so the
pricer is valid both at inception and along a simulated path. The protection
buyer gains when protection is cheap relative to fair value; the seller's MtM is
the exact negative.

Pure numerics; no Qt.
"""

from __future__ import annotations

from datetime import date

import numpy as np
from scipy.optimize import brentq

from duw.domain.instruments import CDS, CdsDirection, Frequency
from duw.domain.market import CreditCurve
from duw.pricing.conventions import (
    add_months,
    build_schedule,
    calendar_for,
    day_count_fraction,
)
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
    df_v = discount_curve.df(valuation_time)
    s_v = survival_curve.survival(valuation_time)
    if s_v <= 0.0:
        return 0.0
    annuity = 0.0
    schedule = build_schedule(
        cds.trade_date,
        cds.maturity_date,
        cds.premium_frequency.per_year,
        calendar_for(cds.currency),
    )
    for period in schedule:
        accr_start = year_fraction(as_of, period.start)
        accr_end = year_fraction(as_of, period.end)
        if accr_end <= valuation_time:
            continue
        accrual = day_count_fraction(period.start, period.end, cds.day_count)
        df_end = discount_curve.df(accr_end) / df_v
        surv_end = survival_curve.survival(accr_end) / s_v
        # Premium paid if the name survives to the payment date.
        annuity += accrual * df_end * surv_end
        # Accrual-on-default over the still-live part of the period: a default
        # at the midpoint pays the premium accrued since the period start.
        live_start = max(accr_start, valuation_time)
        mid = 0.5 * (live_start + accr_end)
        accrued = accrual * (mid - accr_start) / (accr_end - accr_start)
        df_mid = discount_curve.df(mid) / df_v
        marg_pd = (
            survival_curve.survival(live_start) - survival_curve.survival(accr_end)
        ) / s_v
        annuity += accrued * df_mid * marg_pd
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


def standard_cds_maturity(as_of: date, tenor_years: float) -> date:
    """Maturity of a quoted CDS tenor: ``as_of`` plus the tenor in whole months."""
    return add_months(as_of, int(round(tenor_years * 12)))


def bootstrap_cumulative_hazard(
    credit_curve: CreditCurve,
    discount_curve: DiscountCurve,
    as_of: date,
    recovery: float | None = None,
    currency: str = "USD",
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Solve piecewise-flat hazards so each quoted CDS prices at par.

    Node ``i`` sits at the curve time of the tenor's maturity date. Its forward
    hazard is root-found (Brent) so that a quarterly ACT/360 CDS from ``as_of``
    to that maturity, at the quoted spread, has zero value given the hazards
    already fixed for the earlier nodes. Returns ``(node_times, cum_hazards)``.
    """
    r = credit_curve.recovery_rate if recovery is None else recovery
    if not 0.0 <= r < 1.0:
        raise ValueError("recovery must be in [0, 1) to imply a hazard rate")
    order = np.argsort(np.asarray(credit_curve.tenors, dtype=float))
    tenors = [float(credit_curve.tenors[i]) for i in order]
    spreads = [float(credit_curve.spreads[i]) for i in order]
    node_t: list[float] = []
    cum: list[float] = []
    for tenor, spread in zip(tenors, spreads, strict=True):
        maturity = standard_cds_maturity(as_of, tenor)
        t_i = year_fraction(as_of, maturity)
        if node_t and t_i <= node_t[-1]:
            continue
        cds = CDS(
            trade_id="BOOTSTRAP",
            counterparty_id="",
            notional=1.0,
            currency=currency,
            trade_date=as_of,
            maturity_date=maturity,
            reference_entity=credit_curve.issuer,
            direction=CdsDirection.BUY_PROTECTION,
            spread=spread,
            premium_frequency=Frequency.QUARTERLY,
            recovery_rate=r,
        )
        prev_t = node_t[-1] if node_t else 0.0
        prev_h = cum[-1] if cum else 0.0

        def value(lam: float, cds=cds, t_i=t_i, prev_t=prev_t, prev_h=prev_h) -> float:
            curve = SurvivalCurve((*node_t, t_i), (*cum, prev_h + lam * (t_i - prev_t)))
            return price_cds(cds, discount_curve, curve, as_of)

        if spread <= 0.0 or value(0.0) >= 0.0:
            lam = 0.0  # floor: survival must not increase
        else:
            hi = max(4.0 * spread / (1.0 - r), 1e-4)
            while value(hi) < 0.0:
                hi *= 2.0
                if hi > 50.0:
                    raise ValueError(f"cannot bootstrap {credit_curve.issuer} spread")
            lam = brentq(value, 0.0, hi, xtol=1e-14, rtol=1e-12)
        node_t.append(t_i)
        cum.append(prev_h + lam * (t_i - prev_t))
    return tuple(node_t), tuple(cum)
