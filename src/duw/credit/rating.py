"""Internal rating and PD term structure.

Maps a one-year probability of default to an internal rating grade via an
illustrative lookup table, builds a cumulative PD term structure for the
counterparty, and assembles the populated :class:`CreditProfile` from the Merton
and Altman models.

Grade thresholds and the rating-implied PDs below are illustrative S&P-style
values for an educational model, not a calibrated masterscale.

The PD term structure is built, in order of preference:

1. From the counterparty's CDS curve in the snapshot (market-implied), via a
   bootstrapped survival curve: ``PD(t) = 1 - S(t)``.
2. Else from the Merton one-year PD, extrapolated at a constant hazard.
3. Else from the rating-implied one-year PD, extrapolated at a constant hazard.

Pure numerics; no Qt.
"""

from __future__ import annotations

from math import exp, log

from duw.credit.altman import altman_z
from duw.credit.merton import merton_from_financials
from duw.domain.counterparty import Counterparty, CreditProfile
from duw.domain.market import MarketSnapshot
from duw.pricing.curves import DiscountCurve, SurvivalCurve

# Internal grade -> upper bound on the one-year PD for that grade (decimals).
# Ordered best to worst; the first grade whose bound covers the PD is chosen.
GRADE_TABLE: tuple[tuple[str, float], ...] = (
    ("AAA", 0.0002),
    ("AA", 0.0006),
    ("A", 0.0018),
    ("BBB", 0.0040),
    ("BB", 0.0200),
    ("B", 0.1000),
    ("CCC", 0.2500),
    ("CC", 0.5000),
    ("D", 1.0000),
)

# Representative one-year PD per grade, used to extrapolate a term structure when
# only a rating (not a PD) is available.
GRADE_REPRESENTATIVE_PD: dict[str, float] = {
    "AAA": 0.0001,
    "AA": 0.0004,
    "A": 0.0012,
    "BBB": 0.0030,
    "BB": 0.0120,
    "B": 0.0600,
    "CCC": 0.1800,
    "CC": 0.3500,
    "D": 0.9000,
}

# Default tenors (years) at which the PD term structure is reported.
DEFAULT_PD_TENORS: tuple[float, ...] = (0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0)


def pd_to_grade(pd_one_year: float) -> str:
    """Map a one-year PD to an internal grade via :data:`GRADE_TABLE`."""
    pd = min(max(pd_one_year, 0.0), 1.0)
    for grade, upper in GRADE_TABLE:
        if pd <= upper:
            return grade
    return "D"


def _constant_hazard_term_structure(
    pd_one_year: float, tenors: tuple[float, ...] = DEFAULT_PD_TENORS
) -> tuple[tuple[float, float], ...]:
    """Extrapolate a cumulative PD curve from a one-year PD at constant hazard."""
    pd = min(max(pd_one_year, 0.0), 1.0 - 1e-12)
    hazard = -log(1.0 - pd)  # PD(1) = 1 - exp(-hazard)
    return tuple((t, 1.0 - exp(-hazard * t)) for t in tenors)


def pd_term_structure_from_survival(
    survival: SurvivalCurve, tenors: tuple[float, ...] = DEFAULT_PD_TENORS
) -> tuple[tuple[float, float], ...]:
    """Cumulative PD curve ``(t, 1 - S(t))`` from a survival curve."""
    return tuple((t, survival.default_prob(t)) for t in tenors)


def _risk_free_rate(snapshot: MarketSnapshot, currency: str, horizon: float) -> float:
    """Short rate for the counterparty currency, or a default if unavailable."""
    try:
        curve = DiscountCurve.from_yield_curve(snapshot.curve(currency))
    except KeyError:
        return 0.03
    return float(curve.zero_rate(horizon))


def assess_counterparty(
    counterparty: Counterparty,
    snapshot: MarketSnapshot,
    *,
    horizon: float = 1.0,
    asset_drift: float | None = None,
) -> CreditProfile:
    """Assess a counterparty into a fully populated :class:`CreditProfile`."""
    fin = counterparty.financials

    # Merton (only if we have financials).
    asset_value = asset_volatility = dtd = merton_pd = None
    if fin is not None:
        r = _risk_free_rate(snapshot, fin.currency, horizon)
        merton = merton_from_financials(
            fin, r, horizon=horizon, asset_drift=asset_drift
        )
        asset_value = merton.asset_value
        asset_volatility = merton.asset_volatility
        dtd = merton.distance_to_default
        merton_pd = merton.pd

    # Altman (only if we have financials).
    altman_score = altman_zone = None
    if fin is not None:
        altman = altman_z(fin)
        altman_score = altman.z_score
        altman_zone = str(altman.zone)

    # PD term structure and the one-year PD used for grading.
    has_cds = (
        counterparty.cds_issuer is not None
        and counterparty.cds_issuer in snapshot.credit_curves
    )
    if has_cds:
        survival = SurvivalCurve.bootstrap(snapshot.credit(counterparty.cds_issuer))
        pd_term = pd_term_structure_from_survival(survival)
        pd_one_year = survival.default_prob(1.0)
    elif merton_pd is not None:
        pd_term = _constant_hazard_term_structure(merton_pd)
        pd_one_year = merton_pd
    elif counterparty.internal_rating in GRADE_REPRESENTATIVE_PD:
        pd_one_year = GRADE_REPRESENTATIVE_PD[counterparty.internal_rating]
        pd_term = _constant_hazard_term_structure(pd_one_year)
    else:
        pd_one_year = None
        pd_term = ()

    grade = (
        pd_to_grade(pd_one_year)
        if pd_one_year is not None
        else counterparty.internal_rating
    )

    return CreditProfile(
        counterparty_id=counterparty.counterparty_id,
        asset_value=asset_value,
        asset_volatility=asset_volatility,
        distance_to_default=dtd,
        merton_pd=merton_pd,
        altman_z=altman_score,
        altman_zone=altman_zone,
        internal_grade=grade,
        pd_term_structure=pd_term,
    )
