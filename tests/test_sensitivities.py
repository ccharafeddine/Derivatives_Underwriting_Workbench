"""Sensitivities (DV01 / CS01 / FX delta) tests (v3)."""

from __future__ import annotations

from datetime import date

from duw.data.loader import load_market_snapshot, load_seed_counterparties
from duw.domain.instruments import (
    IRS,
    CrossCurrencyDirection,
    CrossCurrencySwap,
    NettingSet,
    SwapDirection,
)
from duw.pipeline.orchestrator import RunConfig
from duw.risk.sensitivities import _bump_credit_spreads, compute_sensitivities

AS_OF = date(2025, 6, 30)


def _counterparty():
    return {c.counterparty_id: c for c in load_seed_counterparties()}["CP001"]


def _config() -> RunConfig:
    return RunConfig(n_paths=1500, n_steps=6, seed=21)


def _irs() -> IRS:
    return IRS(
        trade_id="P",
        counterparty_id="CP001",
        notional=10_000_000.0,
        currency="USD",
        trade_date=AS_OF,
        maturity_date=date(2030, 6, 30),
        fixed_rate=0.043,
        direction=SwapDirection.PAY_FIXED,
    )


def test_bump_credit_spreads_is_absolute() -> None:
    snap = load_market_snapshot()
    issuer = next(iter(snap.credit_curves))
    before = snap.credit(issuer).spreads[0]
    bumped = _bump_credit_spreads(snap, 1.0)  # +1bp
    assert bumped.credit(issuer).spreads[0] == before + 1e-4


def test_sensitivities_populated_and_nonzero_for_irs() -> None:
    sens = compute_sensitivities(
        _counterparty(),
        NettingSet("NS", "CP001", ()),
        _irs(),
        _config(),
        load_market_snapshot(),
    )
    # A payer swap moves with rates and its CVA responds to credit spreads.
    assert sens.dv01_pfe != 0.0
    assert sens.cs01_cva > 0.0  # wider spreads -> more CVA
    assert sens.rate_bump_bps == 1.0


def test_irs_has_negligible_fx_delta() -> None:
    # A single-currency USD swap has no FX exposure.
    sens = compute_sensitivities(
        _counterparty(),
        NettingSet("NS", "CP001", ()),
        _irs(),
        _config(),
        load_market_snapshot(),
    )
    assert sens.fx_delta_pfe == 0.0


def test_sensitivities_tab_renders_result(qapp) -> None:
    from duw.risk.sensitivities import Sensitivities
    from duw.ui.tabs.sensitivities_tab import SensitivitiesTab

    tab = SensitivitiesTab()
    assert not tab.compute_btn.isEnabled()  # disabled until a run completes
    tab.set_ready(True)
    assert tab.compute_btn.isEnabled()
    tab.set_result(
        Sensitivities(
            dv01_pfe=1200.0,
            dv01_cva=-3.5,
            cs01_cva=42.0,
            fx_delta_pfe=0.0,
            fx_delta_cva=0.0,
            rate_bump_bps=1.0,
            spread_bump_bps=1.0,
            fx_bump_pct=1.0,
        )
    )
    assert tab.table.rowCount() == 5
    tab.set_result(None)
    assert tab.table.rowCount() == 0


def test_cross_currency_swap_has_fx_delta() -> None:
    xccy = CrossCurrencySwap(
        trade_id="XC",
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
    sens = compute_sensitivities(
        _counterparty(),
        NettingSet("NS", "CP001", ()),
        xccy,
        _config(),
        load_market_snapshot(),
    )
    assert sens.fx_delta_pfe != 0.0
