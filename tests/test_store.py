"""Deal store and serialization tests (Session 11). Qt-free."""

from __future__ import annotations

from datetime import date

import pytest

from duw.domain.counterparty import Counterparty, Financials
from duw.domain.instruments import (
    CDS,
    IRS,
    CdsDirection,
    FxDirection,
    FXForward,
    NettingSet,
    SwapDirection,
)
from duw.domain.results import AnalysisResults, ExposureProfile, LimitCheck, MemoResult
from duw.store.deals import (
    Deal,
    DealStage,
    DealStore,
    counterparty_from_dict,
    counterparty_to_dict,
    trade_from_dict,
    trade_to_dict,
)

AS_OF = date(2025, 6, 30)


def _irs() -> IRS:
    return IRS(
        trade_id="T1",
        counterparty_id="CP001",
        notional=10_000_000.0,
        currency="USD",
        trade_date=AS_OF,
        maturity_date=date(2030, 6, 30),
        fixed_rate=0.043,
        direction=SwapDirection.PAY_FIXED,
    )


def _counterparty() -> Counterparty:
    return Counterparty(
        counterparty_id="CP001",
        name="Acme Corp",
        sector="Industrials",
        cds_issuer="ACME",
        internal_rating="BBB",
        financials=Financials(
            total_assets=5000.0,
            total_liabilities=3000.0,
            current_assets=2000.0,
            current_liabilities=1200.0,
            retained_earnings=800.0,
            ebit=600.0,
            sales=4000.0,
            market_equity=2500.0,
            equity_volatility=0.30,
        ),
    )


def _results() -> AnalysisResults:
    return AnalysisResults(
        run_config={"seed": 2024, "n_paths": 400, "n_steps": 5},
        counterparty=_counterparty(),
        netting_set=NettingSet("NS", "CP001", (_irs(),)),
        exposure=ExposureProfile(peak_pfe=400_000.0, peak_pfe_time=2.0),
        limits=LimitCheck(limit=5_000_000.0, utilization=0.4, breach=False),
        memo=MemoResult(recommendation="Approve"),
    )


# --------------------------------------------------------------------------- #
# Serialization round-trips
# --------------------------------------------------------------------------- #
def test_trade_roundtrip_irs() -> None:
    trade = _irs()
    back = trade_from_dict(trade_to_dict(trade))
    assert back == trade


def test_trade_roundtrip_fx_and_cds() -> None:
    fx = FXForward(
        trade_id="F1",
        counterparty_id="CP001",
        notional=5e6,
        currency="EUR",
        trade_date=AS_OF,
        maturity_date=date(2027, 6, 30),
        base_currency="EUR",
        quote_currency="USD",
        contract_rate=1.09,
        direction=FxDirection.BUY_BASE,
    )
    cds = CDS(
        trade_id="C1",
        counterparty_id="CP001",
        notional=5e6,
        currency="USD",
        trade_date=AS_OF,
        maturity_date=date(2030, 6, 30),
        reference_entity="ACME",
        direction=CdsDirection.BUY_PROTECTION,
        spread=0.012,
    )
    assert trade_from_dict(trade_to_dict(fx)) == fx
    assert trade_from_dict(trade_to_dict(cds)) == cds


def test_counterparty_roundtrip() -> None:
    cp = _counterparty()
    back = counterparty_from_dict(counterparty_to_dict(cp))
    assert back == cp


# --------------------------------------------------------------------------- #
# Deal <-> results and reopen inputs
# --------------------------------------------------------------------------- #
def test_deal_from_results_and_reopen_inputs() -> None:
    deal = Deal.from_results("Acme IRS", _results())
    assert deal.stage is DealStage.REQUESTED
    assert deal.summary["recommendation"] == "Approve"
    assert deal.summary["counterparty"] == "Acme Corp"

    cp, existing, proposed, config = deal.to_run_inputs()
    assert cp.counterparty_id == "CP001"
    assert len(existing.trades) == 0  # single trade -> it is the proposed one
    assert proposed == _irs()
    assert config.seed == 2024
    assert config.n_paths == 400


# --------------------------------------------------------------------------- #
# Store CRUD
# --------------------------------------------------------------------------- #
def test_store_save_load_roundtrip(tmp_path) -> None:
    store = DealStore(tmp_path / "deals.json")
    deal = Deal.from_results("Acme IRS", _results(), deal_id="d1")
    store.save(deal)
    loaded = store.get("d1")
    assert loaded is not None
    assert loaded.name == "Acme IRS"
    assert loaded.stage is DealStage.REQUESTED
    assert loaded.summary["peak_pfe"] == 400_000.0
    # Round-trips back to valid domain inputs.
    _, _, proposed, _ = loaded.to_run_inputs()
    assert proposed == _irs()


def test_store_stage_transitions(tmp_path) -> None:
    store = DealStore(tmp_path / "deals.json")
    store.save(Deal.from_results("Acme IRS", _results(), deal_id="d1"))
    store.update_stage("d1", DealStage.CREDIT_APPROVED)
    assert store.get("d1").stage is DealStage.CREDIT_APPROVED
    with pytest.raises(KeyError):
        store.update_stage("missing", DealStage.EXECUTED)


def test_store_list_and_delete(tmp_path) -> None:
    store = DealStore(tmp_path / "deals.json")
    store.save(Deal.from_results("A", _results(), deal_id="d1"))
    store.save(Deal.from_results("B", _results(), deal_id="d2"))
    assert {d.deal_id for d in store.list()} == {"d1", "d2"}
    store.delete("d1")
    assert {d.deal_id for d in store.list()} == {"d2"}
    assert store.get("d1") is None


def test_store_upsert_updates_existing(tmp_path) -> None:
    store = DealStore(tmp_path / "deals.json")
    deal = Deal.from_results("A", _results(), deal_id="d1")
    store.save(deal)
    deal.name = "A (renamed)"
    store.save(deal)
    assert len(store.list()) == 1
    assert store.get("d1").name == "A (renamed)"
