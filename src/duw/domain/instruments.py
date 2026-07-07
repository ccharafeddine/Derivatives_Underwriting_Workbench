"""Trade instruments and netting sets.

Defines the :class:`Trade` base plus :class:`IRS`, :class:`FXForward`, and
:class:`CDS` dataclasses and the :class:`NettingSet` that groups a
counterparty's trades under one ISDA master agreement, so exposure is measured
on the *net* position.

All dataclasses are frozen and ``kw_only`` (keyword-only construction keeps
field ordering clean across the base/subclass boundary). No Qt imports; these
are pure data containers with no pricing logic (pricing lives in ``duw.pricing``).

Unit conventions (documented once, relied on everywhere):

- ``notional`` is a positive amount in the trade's ``currency`` (for an
  :class:`FXForward` it is denominated in ``base_currency``).
- Rates and spreads are **decimals**, not basis points or percents
  (``0.03`` == 3%, ``0.01`` == 100 bps).
- Dates are :class:`datetime.date`. ``tenor_years`` uses an ACT/365.25
  convention purely for a quick maturity summary; leg-level day counts are
  carried explicitly on each product for the pricers to use.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum


class SwapDirection(StrEnum):
    """Our side of an interest rate swap."""

    PAY_FIXED = "pay_fixed"  # we pay fixed, receive float
    RECEIVE_FIXED = "receive_fixed"  # we receive fixed, pay float


class FxDirection(StrEnum):
    """Our side of an FX forward, relative to the base currency."""

    BUY_BASE = "buy_base"  # we buy base / sell quote at the contract rate
    SELL_BASE = "sell_base"  # we sell base / buy quote at the contract rate


class CdsDirection(StrEnum):
    """Our side of a credit default swap."""

    BUY_PROTECTION = "buy_protection"  # we pay premium, receive on default
    SELL_PROTECTION = "sell_protection"  # we receive premium, pay on default


class DayCount(StrEnum):
    """Day-count conventions used by leg accruals."""

    ACT_360 = "act/360"
    ACT_365 = "act/365"
    THIRTY_360 = "30/360"


class Frequency(StrEnum):
    """Payment frequency of a leg."""

    ANNUAL = "annual"
    SEMIANNUAL = "semiannual"
    QUARTERLY = "quarterly"
    MONTHLY = "monthly"

    @property
    def per_year(self) -> int:
        """Number of payments per year for this frequency."""
        return {
            Frequency.ANNUAL: 1,
            Frequency.SEMIANNUAL: 2,
            Frequency.QUARTERLY: 4,
            Frequency.MONTHLY: 12,
        }[self]


@dataclass(frozen=True, kw_only=True)
class Trade:
    """Economic terms common to every trade.

    Subclasses add product-specific terms. ``product`` returns the concrete
    class name for display and serialization.
    """

    trade_id: str
    counterparty_id: str
    notional: float
    currency: str
    trade_date: date
    maturity_date: date

    @property
    def product(self) -> str:
        """Short product tag, e.g. ``"IRS"``, ``"FXForward"``, ``"CDS"``."""
        return type(self).__name__

    @property
    def tenor_years(self) -> float:
        """Approximate time to maturity in years (ACT/365.25 summary only)."""
        return (self.maturity_date - self.trade_date).days / 365.25


@dataclass(frozen=True, kw_only=True)
class IRS(Trade):
    """Vanilla fixed-for-floating interest rate swap.

    ``fixed_rate`` and ``float_spread`` are decimals. Direction is expressed
    from our perspective via :class:`SwapDirection`.
    """

    fixed_rate: float
    direction: SwapDirection
    fixed_frequency: Frequency = Frequency.ANNUAL
    float_frequency: Frequency = Frequency.QUARTERLY
    fixed_day_count: DayCount = DayCount.THIRTY_360
    float_day_count: DayCount = DayCount.ACT_360
    float_index: str = "SOFR"
    float_spread: float = 0.0


@dataclass(frozen=True, kw_only=True)
class FXForward(Trade):
    """FX forward exchanging ``base_currency`` for ``quote_currency``.

    ``notional`` (from :class:`Trade`) is in ``base_currency`` and
    ``currency`` should equal ``base_currency``. ``contract_rate`` is the agreed
    forward, quoted as units of ``quote_currency`` per unit of ``base_currency``.
    """

    base_currency: str
    quote_currency: str
    contract_rate: float
    direction: FxDirection


@dataclass(frozen=True, kw_only=True)
class CDS(Trade):
    """Single-name credit default swap.

    ``spread`` is the contractual premium (coupon) in decimals. ``recovery_rate``
    is the assumed recovery on the reference entity used when marking the
    protection leg.
    """

    reference_entity: str
    direction: CdsDirection
    spread: float
    premium_frequency: Frequency = Frequency.QUARTERLY
    day_count: DayCount = DayCount.ACT_360
    recovery_rate: float = 0.4


@dataclass(frozen=True)
class NettingSet:
    """Trades that net under a single ISDA master for one counterparty.

    Frozen: ``add_trade`` returns a new set rather than mutating in place, and
    ``trades`` is a tuple so the set stays hashable and immutable.
    """

    netting_set_id: str
    counterparty_id: str
    trades: tuple[Trade, ...] = ()

    def add_trade(self, trade: Trade) -> NettingSet:
        """Return a new netting set with ``trade`` appended."""
        return replace(self, trades=(*self.trades, trade))

    @property
    def currencies(self) -> tuple[str, ...]:
        """Distinct currencies present in the set, in first-seen order."""
        seen: dict[str, None] = {}
        for t in self.trades:
            seen.setdefault(t.currency, None)
        return tuple(seen)

    def __len__(self) -> int:
        return len(self.trades)
