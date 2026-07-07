"""Market snapshot.

Pure data containers for the market state a single underwriting run is priced
against: zero/discount curves by currency, FX spot rates, per-factor
volatilities, and CDS spread curves by issuer, all as of one date.

No curve math lives here — bootstrapping discount factors, interpolation, and
survival curves is :mod:`duw.pricing.curves` (Session 2). These frozen
dataclasses only hold the inputs. No Qt imports.

Unit conventions:

- ``zero_rates`` are **continuously-compounded** decimals, aligned index-for-
  index with ``tenors`` (year fractions from the as-of date).
- ``spreads`` are decimals (``0.01`` == 100 bps).
- ``fx_spot`` keys are 6-letter pairs like ``"EURUSD"`` meaning units of quote
  (USD) per unit of base (EUR).
- Volatilities are annualized decimals; rate vols are absolute (normal) short-
  rate vols, FX vols are lognormal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class YieldCurve:
    """A zero-rate curve for one currency.

    ``tenors`` and ``zero_rates`` are equal-length, tenor-ascending sequences.
    """

    currency: str
    tenors: tuple[float, ...]
    zero_rates: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.tenors) != len(self.zero_rates):
            raise ValueError(
                f"{self.currency} curve: tenors and zero_rates length mismatch "
                f"({len(self.tenors)} vs {len(self.zero_rates)})"
            )
        if not self.tenors:
            raise ValueError(f"{self.currency} curve: no tenors")


@dataclass(frozen=True)
class CreditCurve:
    """A CDS par-spread curve for one issuer, plus its recovery assumption."""

    issuer: str
    tenors: tuple[float, ...]
    spreads: tuple[float, ...]
    recovery_rate: float = 0.4

    def __post_init__(self) -> None:
        if len(self.tenors) != len(self.spreads):
            raise ValueError(
                f"{self.issuer} credit curve: tenors and spreads length mismatch "
                f"({len(self.tenors)} vs {len(self.spreads)})"
            )
        if not self.tenors:
            raise ValueError(f"{self.issuer} credit curve: no tenors")


@dataclass(frozen=True)
class MarketSnapshot:
    """The full market state for a run, as of ``as_of``.

    Dict-valued fields are keyed by currency (curves, rate vols), issuer
    (credit curves), or FX pair (spot, fx vols). ``frozen=True`` prevents
    reassignment of the containers; treat the contents as read-only.
    """

    as_of: date
    discount_curves: dict[str, YieldCurve] = field(default_factory=dict)
    fx_spot: dict[str, float] = field(default_factory=dict)
    credit_curves: dict[str, CreditCurve] = field(default_factory=dict)
    rate_vols: dict[str, float] = field(default_factory=dict)
    fx_vols: dict[str, float] = field(default_factory=dict)

    def curve(self, currency: str) -> YieldCurve:
        """Return the discount curve for ``currency`` or raise ``KeyError``."""
        try:
            return self.discount_curves[currency]
        except KeyError as exc:
            raise KeyError(f"no discount curve for currency {currency!r}") from exc

    def credit(self, issuer: str) -> CreditCurve:
        """Return the credit curve for ``issuer`` or raise ``KeyError``."""
        try:
            return self.credit_curves[issuer]
        except KeyError as exc:
            raise KeyError(f"no credit curve for issuer {issuer!r}") from exc

    def fx(self, pair: str) -> float:
        """Return the FX spot for ``pair`` (e.g. ``"EURUSD"``) or raise."""
        try:
            return self.fx_spot[pair]
        except KeyError as exc:
            raise KeyError(f"no FX spot for pair {pair!r}") from exc
