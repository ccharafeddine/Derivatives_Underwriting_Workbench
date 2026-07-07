"""Counterparty and credit profile.

Holds who we are facing (:class:`Counterparty`), the balance-sheet inputs that
feed the counterparty-credit models (:class:`Financials`), and the result
container those models populate (:class:`CreditProfile`). The credit math itself
lives in :mod:`duw.credit` (Session 4); here the profile is a container whose
fields all default to ``None`` so it can be constructed empty and filled later.

No Qt imports.

Unit conventions:

- Money fields in :class:`Financials` are in ``currency`` units, all consistent
  (e.g. all in millions). Ratios are formed by the models, not stored here.
- ``equity_volatility`` is an annualized lognormal decimal (``0.30`` == 30%).
- Probabilities of default in :class:`CreditProfile` are decimals in ``[0, 1]``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Financials:
    """Balance-sheet and market inputs for Merton and Altman.

    Merton uses ``market_equity``, ``equity_volatility``, and total liabilities
    (the default point). Altman uses working capital (current assets less
    current liabilities), ``retained_earnings``, ``ebit``, ``market_equity``,
    ``sales``, ``total_assets``, and ``total_liabilities``.
    """

    total_assets: float
    total_liabilities: float
    current_assets: float
    current_liabilities: float
    retained_earnings: float
    ebit: float
    sales: float
    market_equity: float
    equity_volatility: float
    currency: str = "USD"

    @property
    def working_capital(self) -> float:
        """Current assets minus current liabilities."""
        return self.current_assets - self.current_liabilities


@dataclass(frozen=True)
class Counterparty:
    """A trading counterparty.

    ``ticker`` is set for public names whose financials can optionally be
    refreshed via yfinance (always with a synthetic fallback). ``cds_issuer``
    links to a :class:`~duw.domain.market.CreditCurve` in the snapshot when the
    name has a traded CDS. ``internal_rating`` is an optional seeded grade.
    """

    counterparty_id: str
    name: str
    sector: str
    ticker: str | None = None
    financials: Financials | None = None
    cds_issuer: str | None = None
    internal_rating: str | None = None


@dataclass(frozen=True)
class CreditProfile:
    """Result of the counterparty-credit assessment (Step 2).

    Every field defaults to ``None`` so an empty profile can be constructed now
    and populated by :mod:`duw.credit` in a later session. ``pd_term_structure``
    is a sequence of ``(tenor_years, cumulative_pd)`` points.
    """

    counterparty_id: str
    asset_value: float | None = None
    asset_volatility: float | None = None
    distance_to_default: float | None = None
    merton_pd: float | None = None
    altman_z: float | None = None
    altman_zone: str | None = None
    internal_grade: str | None = None
    pd_term_structure: tuple[tuple[float, float], ...] = field(default_factory=tuple)
