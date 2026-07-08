"""Cross-currency swap pricing and exposure-engine integration (v3)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from duw.data.loader import load_market_snapshot
from duw.domain.instruments import (
    CrossCurrencyDirection,
    CrossCurrencySwap,
    Frequency,
    NettingSet,
)
from duw.pricing.curves import DiscountCurve
from duw.pricing.xccy import price_cross_currency_swap
from duw.risk.exposure import ExposureEngine
from duw.store.deals import trade_from_dict, trade_to_dict

AS_OF = date(2025, 6, 30)


def _curves() -> tuple[DiscountCurve, DiscountCurve]:
    snap = load_market_snapshot()
    return (
        DiscountCurve.from_yield_curve(snap.curve("USD")),
        DiscountCurve.from_yield_curve(snap.curve("EUR")),
    )


def _xccy(**kw) -> CrossCurrencySwap:
    base = dict(
        trade_id="XC1",
        counterparty_id="CP001",
        notional=10_000_000.0,
        currency="USD",
        trade_date=AS_OF,
        maturity_date=date(2030, 6, 30),
        foreign_currency="EUR",
        foreign_notional=9_000_000.0,
        base_rate=0.043,
        foreign_rate=0.033,
        direction=CrossCurrencyDirection.RECEIVE_BASE,
    )
    base.update(kw)
    return CrossCurrencySwap(**base)


def test_receive_and_pay_base_are_opposite() -> None:
    usd, eur = _curves()
    fx = 1.08  # USD per EUR
    recv = price_cross_currency_swap(_xccy(), usd, eur, fx, AS_OF)
    pay = price_cross_currency_swap(
        _xccy(direction=CrossCurrencyDirection.PAY_BASE), usd, eur, fx, AS_OF
    )
    assert recv == pytest.approx(-pay)


def test_xccy_is_fx_sensitive() -> None:
    usd, eur = _curves()
    weak_eur = price_cross_currency_swap(_xccy(), usd, eur, 1.00, AS_OF)
    strong_eur = price_cross_currency_swap(_xccy(), usd, eur, 1.20, AS_OF)
    # We receive the USD leg and pay the EUR leg; a stronger EUR raises the value
    # of what we pay, lowering our MtM.
    assert strong_eur < weak_eur


def test_xccy_reprices_toward_zero_past_maturity() -> None:
    usd, eur = _curves()
    # Valued after maturity: no cashflows remain, MtM collapses to 0.
    value = price_cross_currency_swap(
        _xccy(), usd, eur, 1.08, AS_OF, valuation_time=6.0
    )
    assert value == pytest.approx(0.0, abs=1e-6)


def test_xccy_exposure_runs_and_moves_with_fx() -> None:
    ns = NettingSet("NS", "CP001", (_xccy(),))
    engine = ExposureEngine(ns, load_market_snapshot())
    grid = engine.build_time_grid(8)
    cube = engine.simulate_cube(grid, n_paths=1000, seed=4)
    assert cube.shape == (1000, len(grid))
    # Exposure must vary across paths (the FX/rate factors move the MtM).
    assert np.maximum(cube, 0.0).std() > 0.0


def test_xccy_resolves_reverse_fx_pair() -> None:
    # EUR-base / USD-foreign: the snapshot only carries EURUSD, so the engine
    # must resolve and invert the reverse pair without error.
    swap = _xccy(currency="EUR", foreign_currency="USD")
    engine = ExposureEngine(NettingSet("NS", "CP001", (swap,)), load_market_snapshot())
    grid = engine.build_time_grid(6)
    cube = engine.simulate_cube(grid, n_paths=400, seed=9)
    assert np.isfinite(cube).all()


def test_xccy_round_trips_through_deal_store() -> None:
    swap = _xccy(frequency=Frequency.SEMIANNUAL, exchange_notional=False)
    assert trade_from_dict(trade_to_dict(swap)) == swap
