"""Swaption pricing and exposure-engine integration (v3)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from duw.data.loader import load_market_snapshot
from duw.domain.instruments import (
    Frequency,
    NettingSet,
    Swaption,
    SwaptionDirection,
)
from duw.pricing.curves import DiscountCurve
from duw.pricing.swaption import forward_swap_rate_and_annuity, price_swaption
from duw.risk.exposure import ExposureEngine
from duw.store.deals import trade_from_dict, trade_to_dict

AS_OF = date(2025, 6, 30)


def _curve() -> DiscountCurve:
    return DiscountCurve.from_yield_curve(load_market_snapshot().curve("USD"))


def _swaption(**kw) -> Swaption:
    base = dict(
        trade_id="SW1",
        counterparty_id="CP001",
        notional=10_000_000.0,
        currency="USD",
        trade_date=AS_OF,
        maturity_date=date(2027, 6, 30),  # 2y expiry
        strike=0.043,
        direction=SwaptionDirection.PAYER,
        underlying_tenor_years=5.0,
        volatility=0.20,
    )
    base.update(kw)
    return Swaption(**base)


def test_swaption_value_is_positive_when_bought() -> None:
    value = price_swaption(_swaption(), _curve(), AS_OF)
    assert value > 0.0


def test_sold_swaption_is_negative_of_bought() -> None:
    curve = _curve()
    bought = price_swaption(_swaption(bought=True), curve, AS_OF)
    sold = price_swaption(_swaption(bought=False), curve, AS_OF)
    assert sold == pytest.approx(-bought)


def test_swaption_rises_with_volatility() -> None:
    curve = _curve()
    low = price_swaption(_swaption(volatility=0.10), curve, AS_OF)
    high = price_swaption(_swaption(volatility=0.40), curve, AS_OF)
    assert high > low


def test_payer_receiver_parity_at_the_money_forward() -> None:
    # At K = forward swap rate, payer and receiver swaption values are equal.
    curve = _curve()
    expiry_t = 2.0
    fwd, _ = forward_swap_rate_and_annuity(curve, expiry_t, 5.0, 1, 0.0)
    payer = price_swaption(
        _swaption(strike=fwd, direction=SwaptionDirection.PAYER), curve, AS_OF
    )
    receiver = price_swaption(
        _swaption(strike=fwd, direction=SwaptionDirection.RECEIVER), curve, AS_OF
    )
    assert payer == pytest.approx(receiver, rel=1e-6)


def test_swaption_zero_after_expiry() -> None:
    # Priced past the 2y expiry -> cash-settled, no residual MtM.
    assert price_swaption(_swaption(), _curve(), AS_OF, valuation_time=3.0) == 0.0


def test_swaption_exposure_runs_and_is_nonnegative() -> None:
    ns = NettingSet("NS", "CP001", (_swaption(),))
    engine = ExposureEngine(ns, load_market_snapshot())
    grid = engine.build_time_grid(8)
    cube = engine.simulate_cube(grid, n_paths=800, seed=5)
    exposure = np.maximum(cube, 0.0)
    assert exposure.shape == (800, len(grid))
    # A bought option always has non-negative value -> exposure equals |MtM|.
    assert (cube >= -1e-6).all()
    assert exposure.max() > 0.0


def test_swaption_round_trips_through_deal_store() -> None:
    sw = _swaption(underlying_frequency=Frequency.SEMIANNUAL, bought=False)
    restored = trade_from_dict(trade_to_dict(sw))
    assert restored == sw
