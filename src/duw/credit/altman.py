"""Altman Z-score.

The original Altman (1968) Z-score for public manufacturers:

    Z = 1.2 X1 + 1.4 X2 + 3.3 X3 + 0.6 X4 + 1.0 X5

with
    X1 = working capital / total assets
    X2 = retained earnings / total assets
    X3 = EBIT / total assets
    X4 = market value of equity / total liabilities
    X5 = sales / total assets

Zones: ``Z > 2.99`` safe, ``1.81 <= Z <= 2.99`` grey, ``Z < 1.81`` distress.
This is one classic variant among several (Z', Z''); the coefficients here are
the widely-cited originals and are illustrative, not calibrated to any book.

Pure numerics; no Qt.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from duw.domain.counterparty import Financials

SAFE_THRESHOLD = 2.99
DISTRESS_THRESHOLD = 1.81


class AltmanZone(StrEnum):
    """Altman credit-health zone."""

    SAFE = "safe"
    GREY = "grey"
    DISTRESS = "distress"


@dataclass(frozen=True)
class AltmanResult:
    """Z-score, its five components, and the resulting zone."""

    z_score: float
    x1: float
    x2: float
    x3: float
    x4: float
    x5: float
    zone: AltmanZone


def classify_zone(z: float) -> AltmanZone:
    """Map a Z-score to its zone."""
    if z > SAFE_THRESHOLD:
        return AltmanZone.SAFE
    if z < DISTRESS_THRESHOLD:
        return AltmanZone.DISTRESS
    return AltmanZone.GREY


def altman_z(financials: Financials) -> AltmanResult:
    """Compute the Altman Z-score from a counterparty's financials."""
    ta = financials.total_assets
    tl = financials.total_liabilities
    if ta <= 0.0 or tl <= 0.0:
        raise ValueError("total assets and total liabilities must be positive")

    x1 = financials.working_capital / ta
    x2 = financials.retained_earnings / ta
    x3 = financials.ebit / ta
    x4 = financials.market_equity / tl
    x5 = financials.sales / ta
    z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5
    return AltmanResult(
        z_score=z, x1=x1, x2=x2, x3=x3, x4=x4, x5=x5, zone=classify_zone(z)
    )
