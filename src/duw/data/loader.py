"""Loaders for the bundled synthetic market snapshot and seed counterparties.

Reads the JSON files packaged alongside this module into the domain dataclasses.
Fully offline: no network calls, no yfinance. A caller may point the loaders at
an alternative file, but the default is the bundled data resolved via
:mod:`importlib.resources` so it works whether the package is run from source or
installed as a wheel.

No Qt imports.
"""

from __future__ import annotations

import json
from datetime import date
from importlib import resources
from pathlib import Path
from typing import Any

from duw.domain.counterparty import Counterparty, Financials
from duw.domain.market import CreditCurve, MarketSnapshot, YieldCurve

MARKET_SNAPSHOT_FILE = "market_snapshot.json"
COUNTERPARTIES_FILE = "counterparties.json"


def _read_bundled(filename: str) -> dict[str, Any]:
    """Read and parse a JSON file bundled in ``duw.data``."""
    resource = resources.files("duw.data").joinpath(filename)
    with resources.as_file(resource) as path:
        return json.loads(path.read_text(encoding="utf-8"))


def _read_path(path: str | Path) -> dict[str, Any]:
    """Read and parse a JSON file from an explicit filesystem path."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_market_snapshot(path: str | Path | None = None) -> MarketSnapshot:
    """Load a :class:`MarketSnapshot` from JSON.

    Uses the bundled snapshot when ``path`` is ``None``.
    """
    raw = _read_path(path) if path is not None else _read_bundled(MARKET_SNAPSHOT_FILE)

    discount_curves = {
        ccy: YieldCurve(
            currency=c["currency"],
            tenors=tuple(c["tenors"]),
            zero_rates=tuple(c["zero_rates"]),
        )
        for ccy, c in raw["discount_curves"].items()
    }
    credit_curves = {
        issuer: CreditCurve(
            issuer=c["issuer"],
            tenors=tuple(c["tenors"]),
            spreads=tuple(c["spreads"]),
            recovery_rate=c.get("recovery_rate", 0.4),
        )
        for issuer, c in raw["credit_curves"].items()
    }
    return MarketSnapshot(
        as_of=date.fromisoformat(raw["as_of"]),
        discount_curves=discount_curves,
        fx_spot=dict(raw.get("fx_spot", {})),
        credit_curves=credit_curves,
        rate_vols=dict(raw.get("rate_vols", {})),
        fx_vols=dict(raw.get("fx_vols", {})),
    )


def load_seed_counterparties(path: str | Path | None = None) -> list[Counterparty]:
    """Load the synthetic seed counterparties from JSON.

    Uses the bundled file when ``path`` is ``None``.
    """
    raw = _read_path(path) if path is not None else _read_bundled(COUNTERPARTIES_FILE)

    counterparties: list[Counterparty] = []
    for entry in raw["counterparties"]:
        fin_raw = entry.get("financials")
        financials = Financials(**fin_raw) if fin_raw is not None else None
        counterparties.append(
            Counterparty(
                counterparty_id=entry["counterparty_id"],
                name=entry["name"],
                sector=entry["sector"],
                ticker=entry.get("ticker"),
                financials=financials,
                cds_issuer=entry.get("cds_issuer"),
                internal_rating=entry.get("internal_rating"),
            )
        )
    return counterparties
