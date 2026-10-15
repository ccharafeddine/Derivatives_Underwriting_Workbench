"""Compact number formatting for the Graphite views (KPI strip, overview)."""

from __future__ import annotations

import math

_MINUS = "\u2212"


def _bad(x: float | None) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def short_money(x: float | None, signed: bool = False) -> str:
    """``3.86M``, ``482K``, ``-48,210``-style compact amounts (true minus sign)."""
    if _bad(x):
        return "—"
    a = abs(x)
    if a >= 1e9:
        body = f"{a / 1e9:.2f}B"
    elif a >= 1e6:
        body = f"{a / 1e6:.2f}M"
    elif a >= 1e5:
        body = f"{a / 1e3:.0f}K"
    else:
        body = f"{a:,.0f}"
    if x < 0:
        return _MINUS + body
    return ("+" + body) if signed and x > 0 else body


def full_money(x: float | None, signed: bool = False) -> str:
    """``1,234,567`` with a true minus sign (and ``+`` when ``signed``)."""
    if _bad(x):
        return "—"
    body = f"{abs(x):,.0f}"
    if x < 0:
        return _MINUS + body
    return ("+" + body) if signed and x > 0 else body


def pct(x: float | None, decimals: int = 0) -> str:
    return "—" if _bad(x) else f"{x:.{decimals}%}"


def tone(x: float | None) -> str | None:
    """``"pos"`` / ``"neg"`` for a P&L-style amount (``None`` when flat/unknown)."""
    if _bad(x) or x == 0:
        return None
    return "pos" if x > 0 else "neg"
