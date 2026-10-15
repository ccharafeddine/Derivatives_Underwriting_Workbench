"""Day-count conventions, holiday calendars, and accrual schedules.

Pure numerics, no Qt. Three pieces back every dated leg:

- :func:`day_count_fraction`: the accrual fraction between two dates under
  ACT/360, ACT/365 (Fixed), or 30/360 (US bond basis), matching QuantLib's
  ``Actual360``, ``Actual365Fixed`` and ``Thirty360(BondBasis)``.
- :class:`Calendar`: weekend plus holiday rules for the main money-market
  centres (``USNY``, ``TARGET``, ``LONDON``), with a weekends-only fallback.
  These are the *basic* fixed and moveable public holidays. Ad-hoc closures
  (national days of mourning, one-off bank holidays) are not modelled.
- :func:`build_schedule`: backward-generated accrual periods from maturity,
  with a short front stub if needed, and business-day adjusted dates
  (modified following by default). The pricer gets adjusted accrual start/end
  dates and accrues each period with the leg's own day count.

Curve time (``year_fraction`` in :mod:`duw.pricing.curves`) is a separate axis
and is not affected by the leg day counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from functools import lru_cache

from duw.domain.instruments import DayCount


class BusinessDayConvention(StrEnum):
    """How a date falling on a non-business day is rolled."""

    UNADJUSTED = "unadjusted"
    FOLLOWING = "following"
    MODIFIED_FOLLOWING = "modified_following"
    PRECEDING = "preceding"


# --------------------------------------------------------------------------- #
# Day counts
# --------------------------------------------------------------------------- #
def day_count_fraction(d1: date, d2: date, convention: DayCount) -> float:
    """Accrual fraction from ``d1`` to ``d2`` under ``convention``."""
    if convention is DayCount.ACT_360:
        return (d2 - d1).days / 360.0
    if convention is DayCount.ACT_365:
        return (d2 - d1).days / 365.0
    if convention is DayCount.THIRTY_360:
        # 30/360 US bond basis (ISDA 2006 "30/360"), as QuantLib BondBasis.
        dd1, dd2 = d1.day, d2.day
        if dd1 == 31:
            dd1 = 30
        if dd2 == 31 and dd1 == 30:
            dd2 = 30
        days = 360 * (d2.year - d1.year) + 30 * (d2.month - d1.month) + (dd2 - dd1)
        return days / 360.0
    raise ValueError(f"unsupported day count: {convention}")


# --------------------------------------------------------------------------- #
# Calendars
# --------------------------------------------------------------------------- #
def _easter_sunday(year: int) -> date:
    """Gregorian Easter (anonymous Gregorian algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month, day = divmod(h + ell - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """``n``-th ``weekday`` (Mon=0) of the month; ``n = -1`` for the last."""
    if n > 0:
        first = date(year, month, 1)
        offset = (weekday - first.weekday()) % 7
        return first + timedelta(days=offset + 7 * (n - 1))
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    last = nxt - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _us_observed(d: date) -> date:
    """Federal Reserve rule: a Sunday holiday moves to Monday; Saturday is not moved."""
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def _usny(year: int) -> set[date]:
    hol = {
        _us_observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),  # Presidents' Day
        _nth_weekday(year, 5, 0, -1),  # Memorial Day
        _us_observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 10, 0, 2),  # Columbus Day
        _us_observed(date(year, 11, 11)),  # Veterans Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _us_observed(date(year, 12, 25)),
    }
    if year >= 2022:
        hol.add(_us_observed(date(year, 6, 19)))  # Juneteenth
    return hol


def _target(year: int) -> set[date]:
    easter = _easter_sunday(year)
    return {
        date(year, 1, 1),
        easter - timedelta(days=2),  # Good Friday
        easter + timedelta(days=1),  # Easter Monday
        date(year, 5, 1),
        date(year, 12, 25),
        date(year, 12, 26),
    }


def _uk_substitute(d: date, taken: set[date]) -> date:
    while d.weekday() >= 5 or d in taken:
        d += timedelta(days=1)
    return d


def _london(year: int) -> set[date]:
    easter = _easter_sunday(year)
    hol: set[date] = set()
    hol.add(_uk_substitute(date(year, 1, 1), hol))
    hol.add(easter - timedelta(days=2))
    hol.add(easter + timedelta(days=1))
    hol.add(_nth_weekday(year, 5, 0, 1))  # Early May bank holiday
    hol.add(_nth_weekday(year, 5, 0, -1))  # Spring bank holiday
    hol.add(_nth_weekday(year, 8, 0, -1))  # Summer bank holiday
    xmas = _uk_substitute(date(year, 12, 25), hol)
    hol.add(xmas)
    hol.add(_uk_substitute(date(year, 12, 26), hol))
    return hol


_RULES = {"USNY": _usny, "TARGET": _target, "LONDON": _london, "WEEKENDS": None}
_CURRENCY_CALENDAR = {"USD": "USNY", "EUR": "TARGET", "GBP": "LONDON"}


@dataclass(frozen=True)
class Calendar:
    """A business-day calendar: Saturdays, Sundays and the named holiday rules."""

    name: str = "WEEKENDS"

    def __post_init__(self) -> None:
        if self.name not in _RULES:
            raise ValueError(f"unknown calendar: {self.name}")

    def holidays(self, year: int) -> frozenset[date]:
        """Weekday holidays in ``year`` for this calendar."""
        return _holidays(self.name, year)

    def is_business_day(self, d: date) -> bool:
        """True when ``d`` is neither a weekend nor a holiday."""
        return d.weekday() < 5 and d not in _holidays(self.name, d.year)

    def adjust(
        self,
        d: date,
        convention: BusinessDayConvention = BusinessDayConvention.MODIFIED_FOLLOWING,
    ) -> date:
        """Roll ``d`` to a business day under ``convention``."""
        if convention is BusinessDayConvention.UNADJUSTED or self.is_business_day(d):
            return d
        if convention is BusinessDayConvention.PRECEDING:
            return self._step(d, -1)
        rolled = self._step(d, 1)
        if (
            convention is BusinessDayConvention.MODIFIED_FOLLOWING
            and rolled.month != d.month
        ):
            return self._step(d, -1)
        return rolled

    def _step(self, d: date, direction: int) -> date:
        while not self.is_business_day(d):
            d += timedelta(days=direction)
        return d


@lru_cache(maxsize=512)
def _holidays(name: str, year: int) -> frozenset[date]:
    rule = _RULES[name]
    return frozenset() if rule is None else frozenset(rule(year))


WEEKENDS_ONLY = Calendar("WEEKENDS")


def calendar_for(currency: str) -> Calendar:
    """Default calendar for a currency (weekends-only when not covered)."""
    return Calendar(_CURRENCY_CALENDAR.get(currency.upper(), "WEEKENDS"))


# --------------------------------------------------------------------------- #
# Schedules
# --------------------------------------------------------------------------- #
def add_months(d: date, months: int) -> date:
    """Shift ``d`` by whole months, clamping the day to the month's length."""
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    last_day = (nxt - timedelta(days=1)).day
    return date(year, month, min(d.day, last_day))


@dataclass(frozen=True)
class AccrualPeriod:
    """One accrual period: adjusted start/end dates (payment at ``end``)."""

    start: date
    end: date


# A front stub shorter than this merges into the following period (long stub).
_MIN_STUB_DAYS = 7


@lru_cache(maxsize=4096)
def build_schedule(
    start: date,
    end: date,
    per_year: int,
    calendar: Calendar = WEEKENDS_ONLY,
    convention: BusinessDayConvention = BusinessDayConvention.MODIFIED_FOLLOWING,
) -> tuple[AccrualPeriod, ...]:
    """Backward-generated, business-day adjusted accrual periods.

    Unadjusted roll dates step back from ``end`` in ``12 / per_year`` months;
    any front stub shorter than a week merges into the first full period
    (QuantLib would keep it as a short stub). Every date, including the
    effective date, is business-day adjusted.
    Always returns at least one period.
    """
    if end <= start:
        raise ValueError("schedule end must be after start")
    step = 12 // per_year
    rolls = [end]
    k = 1
    while True:
        d = add_months(end, -step * k)
        if d <= start:
            break
        rolls.append(d)
        k += 1
    rolls.reverse()
    if (rolls[0] - start).days < _MIN_STUB_DAYS and len(rolls) > 1:
        rolls = rolls[1:]
    dates = [calendar.adjust(d, convention) for d in (start, *rolls)]
    pairs = zip(dates[:-1], dates[1:], strict=True)
    return tuple(AccrualPeriod(a, b) for a, b in pairs if b > a)
