"""Scenario shock tests (v2)."""

from __future__ import annotations

from datetime import date

import pytest

from duw.data.loader import load_market_snapshot, load_seed_counterparties
from duw.domain.instruments import IRS, NettingSet, SwapDirection
from duw.pipeline.orchestrator import RunConfig, run_pipeline
from duw.risk.scenarios import ScenarioSpec, apply_scenario

AS_OF = date(2025, 6, 30)


def test_base_scenario_is_unchanged() -> None:
    snap = load_market_snapshot()
    shocked = apply_scenario(snap, ScenarioSpec())
    assert shocked is snap  # base short-circuits
    assert ScenarioSpec().is_base


def test_parallel_rate_shift() -> None:
    snap = load_market_snapshot()
    shocked = apply_scenario(snap, ScenarioSpec(rate_shift_bps=100.0))
    base = snap.curve("USD").zero_rates
    bumped = shocked.curve("USD").zero_rates
    for r0, r1 in zip(base, bumped, strict=True):
        assert r1 == pytest.approx(r0 + 0.01)


def test_steepener_rotates_the_curve() -> None:
    snap = load_market_snapshot()
    shocked = apply_scenario(snap, ScenarioSpec(steepen_bps=100.0))
    base = snap.curve("USD")
    new = shocked.curve("USD")
    # Short end falls, long end rises under a steepener.
    assert new.zero_rates[0] < base.zero_rates[0]
    assert new.zero_rates[-1] > base.zero_rates[-1]
    # Total twist between ends equals the requested steepening.
    twist = (new.zero_rates[-1] - base.zero_rates[-1]) - (
        new.zero_rates[0] - base.zero_rates[0]
    )
    assert twist == pytest.approx(0.01)


def test_fx_and_spread_shocks() -> None:
    snap = load_market_snapshot()
    shocked = apply_scenario(
        snap, ScenarioSpec(fx_shock_pct=-10.0, spread_widen_pct=50.0)
    )
    assert shocked.fx("EURUSD") == pytest.approx(snap.fx("EURUSD") * 0.90)
    base_acme = snap.credit("ACME").spreads
    wide_acme = shocked.credit("ACME").spreads
    for s0, s1 in zip(base_acme, wide_acme, strict=True):
        assert s1 == pytest.approx(s0 * 1.5)


def test_stressed_pipeline_differs_from_base() -> None:
    snap = load_market_snapshot()
    cp = {c.counterparty_id: c for c in load_seed_counterparties()}["CP001"]
    proposed = IRS(
        trade_id="P1",
        counterparty_id="CP001",
        notional=10_000_000.0,
        currency="USD",
        trade_date=AS_OF,
        maturity_date=date(2030, 6, 30),
        fixed_rate=0.043,
        direction=SwapDirection.PAY_FIXED,
    )
    empty = NettingSet("NS", "CP001", ())
    cfg = RunConfig(n_paths=800, n_steps=6, seed=2024)

    base = run_pipeline(cp, empty, proposed, cfg, snapshot=snap)
    stressed_snap = apply_scenario(snap, ScenarioSpec(rate_shift_bps=200.0))
    stressed = run_pipeline(cp, empty, proposed, cfg, snapshot=stressed_snap)

    # A +200bp shift changes a payer swap's exposure materially.
    assert stressed.exposure.peak_pfe != base.exposure.peak_pfe
    assert stressed.exposure.peak_pfe > 0.0
