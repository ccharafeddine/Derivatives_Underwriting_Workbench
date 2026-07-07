"""Bundled-data loader tests (Session 1). Must run fully offline."""

from __future__ import annotations

from datetime import date

from duw.data.loader import load_market_snapshot, load_seed_counterparties
from duw.domain.counterparty import Counterparty
from duw.domain.market import MarketSnapshot


def test_load_bundled_market_snapshot() -> None:
    snap = load_market_snapshot()
    assert isinstance(snap, MarketSnapshot)
    assert snap.as_of == date(2025, 6, 30)
    # Curves present and internally consistent.
    usd = snap.curve("USD")
    assert len(usd.tenors) == len(usd.zero_rates)
    assert snap.curve("EUR").currency == "EUR"
    assert snap.fx("EURUSD") > 0
    acme = snap.credit("ACME")
    assert acme.recovery_rate == 0.4
    assert len(acme.spreads) == len(acme.tenors)
    assert snap.rate_vols["USD"] > 0


def test_load_seed_counterparties() -> None:
    cps = load_seed_counterparties()
    assert len(cps) == 4
    assert all(isinstance(c, Counterparty) for c in cps)
    by_id = {c.counterparty_id: c for c in cps}
    acme = by_id["CP001"]
    assert acme.financials is not None
    assert acme.financials.total_assets > acme.financials.total_liabilities
    assert acme.cds_issuer == "ACME"
    # CP004 has no CDS issuer and no ticker (private, no traded credit).
    assert by_id["CP004"].cds_issuer is None


def test_seed_credit_issuers_resolve_in_snapshot() -> None:
    snap = load_market_snapshot()
    for cp in load_seed_counterparties():
        if cp.cds_issuer is not None:
            # Every referenced issuer must exist in the bundled snapshot.
            assert snap.credit(cp.cds_issuer).issuer == cp.cds_issuer
