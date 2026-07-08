"""Ready-made example deals for learning and demonstration.

Each example names a synthetic seed counterparty and a proposed trade (optionally
with a book of existing trades) that illustrates a distinct situation: an
investment-grade swap, a distressed-name CDS, a limit-breaching trade, and a
netted book. Pure data; no Qt. The UI loads these into the input tabs so a new
user can run a full analysis in one click.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from duw.domain.instruments import (
    CDS,
    IRS,
    CdsDirection,
    FxDirection,
    FXForward,
    SwapDirection,
    Trade,
)

# Matches the bundled market snapshot's as-of date.
_AS_OF = date(2025, 6, 30)
_MAT_5Y = date(2030, 6, 30)
_MAT_3Y = date(2028, 6, 30)


@dataclass(frozen=True)
class Example:
    """A named, preconfigured deal that loads into the input tabs."""

    name: str
    description: str
    counterparty_id: str
    trade: Trade
    book: tuple[Trade, ...] = field(default_factory=tuple)


def examples() -> list[Example]:
    """Return the built-in example deals."""
    return [
        Example(
            name="Investment-grade payer swap",
            description=(
                "A vanilla 5y payer interest rate swap against a strong "
                "technology name — a clean, within-limit trade."
            ),
            counterparty_id="CP002",
            trade=IRS(
                trade_id="EX-IRS",
                counterparty_id="CP002",
                notional=10_000_000.0,
                currency="USD",
                trade_date=_AS_OF,
                maturity_date=_MAT_5Y,
                fixed_rate=0.043,
                direction=SwapDirection.PAY_FIXED,
            ),
        ),
        Example(
            name="Distressed-name CDS protection",
            description=(
                "Buying 5y protection on a distressed financial name — see how a "
                "weak counterparty and wide spreads drive CVA."
            ),
            counterparty_id="CP003",
            trade=CDS(
                trade_id="EX-CDS",
                counterparty_id="CP003",
                notional=5_000_000.0,
                currency="USD",
                trade_date=_AS_OF,
                maturity_date=_MAT_5Y,
                reference_entity="INITECH",
                direction=CdsDirection.BUY_PROTECTION,
                spread=0.02,
            ),
        ),
        Example(
            name="Limit-breaching swap",
            description=(
                "A very large payer swap whose peak PFE blows through the "
                "counterparty limit — watch the breach flag."
            ),
            counterparty_id="CP001",
            trade=IRS(
                trade_id="EX-BREACH",
                counterparty_id="CP001",
                notional=150_000_000.0,
                currency="USD",
                trade_date=_AS_OF,
                maturity_date=_MAT_5Y,
                fixed_rate=0.043,
                direction=SwapDirection.PAY_FIXED,
            ),
        ),
        Example(
            name="Netted book (offsetting trade)",
            description=(
                "An existing payer swap plus a proposed offsetting receiver on "
                "the same terms — the incremental exposure nets to near zero."
            ),
            counterparty_id="CP001",
            trade=IRS(
                trade_id="EX-RECV",
                counterparty_id="CP001",
                notional=10_000_000.0,
                currency="USD",
                trade_date=_AS_OF,
                maturity_date=_MAT_5Y,
                fixed_rate=0.043,
                direction=SwapDirection.RECEIVE_FIXED,
            ),
            book=(
                IRS(
                    trade_id="EX-BOOK",
                    counterparty_id="CP001",
                    notional=10_000_000.0,
                    currency="USD",
                    trade_date=_AS_OF,
                    maturity_date=_MAT_5Y,
                    fixed_rate=0.043,
                    direction=SwapDirection.PAY_FIXED,
                ),
            ),
        ),
        Example(
            name="FX forward",
            description=(
                "A 3y EUR/USD forward against an energy name — exposure driven by "
                "the FX move rather than rates."
            ),
            counterparty_id="CP004",
            trade=FXForward(
                trade_id="EX-FX",
                counterparty_id="CP004",
                notional=8_000_000.0,
                currency="EUR",
                trade_date=_AS_OF,
                maturity_date=_MAT_3Y,
                base_currency="EUR",
                quote_currency="USD",
                contract_rate=1.10,
                direction=FxDirection.BUY_BASE,
            ),
        ),
    ]
