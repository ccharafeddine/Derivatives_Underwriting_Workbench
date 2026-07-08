"""Pipeline orchestrator tests (Session 7)."""

from __future__ import annotations

import json
from datetime import date

import pytest

from duw.data.loader import load_seed_counterparties
from duw.domain.instruments import IRS, NettingSet, SwapDirection
from duw.pipeline.orchestrator import Orchestrator, RunConfig, run_pipeline

AS_OF = date(2025, 6, 30)

# Small but stable settings to keep the end-to-end run fast.
FAST = RunConfig(n_paths=400, n_steps=5, seed=2024, limit=5_000_000.0)


def _counterparties() -> dict:
    return {c.counterparty_id: c for c in load_seed_counterparties()}


def _proposed_irs() -> IRS:
    return IRS(
        trade_id="NEW1",
        counterparty_id="CP001",
        notional=10_000_000.0,
        currency="USD",
        trade_date=AS_OF,
        maturity_date=date(2030, 6, 30),
        fixed_rate=0.043,
        direction=SwapDirection.PAY_FIXED,
    )


def _empty_set(cp_id: str = "CP001") -> NettingSet:
    return NettingSet(netting_set_id="NS1", counterparty_id=cp_id, trades=())


def test_full_pipeline_populates_every_substep() -> None:
    cp = _counterparties()["CP001"]
    results = run_pipeline(cp, _empty_set(), _proposed_irs(), FAST)
    assert results.snapshot is not None
    assert results.netting_set is not None and len(results.netting_set) == 1
    assert results.credit_profile is not None
    assert results.exposure is not None
    assert results.collateral is not None
    assert results.cva is not None
    assert results.limits is not None
    assert results.memo is not None  # stub populated
    assert results.run_config["seed"] == FAST.seed
    assert len(results.messages) >= 8  # one log line per major step


def test_fixed_seed_is_reproducible() -> None:
    cp = _counterparties()["CP001"]
    a = run_pipeline(cp, _empty_set(), _proposed_irs(), FAST)
    b = run_pipeline(cp, _empty_set(), _proposed_irs(), FAST)
    assert a.exposure.peak_pfe == b.exposure.peak_pfe
    assert a.exposure.ee == b.exposure.ee
    assert a.cva.cva == b.cva.cva
    assert a.limits.proposed_peak_pfe == b.limits.proposed_peak_pfe


def test_progress_callback_is_monotone_and_completes() -> None:
    cp = _counterparties()["CP001"]
    events: list[tuple[float, str]] = []
    run_pipeline(
        cp,
        _empty_set(),
        _proposed_irs(),
        FAST,
        progress_callback=lambda f, m: events.append((f, m)),
    )
    fractions = [f for f, _ in events]
    assert len(events) == 12  # one per pipeline step
    assert fractions == sorted(fractions)
    assert fractions[-1] == pytest.approx(1.0)
    assert all(isinstance(m, str) and m for _, m in events)


def test_run_config_is_saved_as_json(tmp_path) -> None:
    cp = _counterparties()["CP001"]
    results = run_pipeline(cp, _empty_set(), _proposed_irs(), FAST, output_dir=tmp_path)
    saved = tmp_path / "run_config.json"
    assert saved.exists()
    payload = json.loads(saved.read_text(encoding="utf-8"))
    assert payload["run_config"]["seed"] == FAST.seed
    assert payload["run_config"]["n_paths"] == FAST.n_paths
    assert "peak_pfe" in payload["summary"]
    assert payload["summary"]["peak_pfe"] == pytest.approx(results.exposure.peak_pfe)


def test_csa_config_reduces_collateralized_exposure() -> None:
    cp = _counterparties()["CP001"]
    cfg = RunConfig(
        n_paths=400,
        n_steps=5,
        seed=2024,
        csa_threshold=100_000.0,
        csa_initial_margin=50_000.0,
    )
    results = run_pipeline(cp, _empty_set(), _proposed_irs(), cfg)
    collat = results.collateral
    assert collat.peak_pfe_collateralized < collat.peak_pfe_uncollateralized


def test_tiny_limit_flags_breach() -> None:
    cp = _counterparties()["CP001"]
    cfg = RunConfig(n_paths=400, n_steps=5, seed=2024, limit=1_000.0)
    results = run_pipeline(cp, _empty_set(), _proposed_irs(), cfg)
    assert results.limits.breach is True
    assert results.limits.utilization > 1.0


def test_counterparty_without_cds_still_prices_cva() -> None:
    cp = _counterparties()["CP004"]  # no cds_issuer, has financials
    proposed = IRS(
        trade_id="NEW2",
        counterparty_id="CP004",
        notional=8_000_000.0,
        currency="EUR",
        trade_date=AS_OF,
        maturity_date=date(2029, 6, 30),
        fixed_rate=0.031,
        direction=SwapDirection.PAY_FIXED,
    )
    results = run_pipeline(cp, _empty_set("CP004"), proposed, FAST)
    assert results.credit_profile.merton_pd is not None
    assert results.cva.cva >= 0.0
    assert results.cva.cva == results.cva.cva  # not NaN


def test_orchestrator_class_matches_wrapper() -> None:
    cp = _counterparties()["CP001"]
    orch = Orchestrator(FAST)
    results = orch.run(cp, _empty_set(), _proposed_irs())
    assert results.exposure is not None
    assert results.cva is not None
