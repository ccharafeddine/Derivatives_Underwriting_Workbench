"""Limit and netting check tests (Session 6)."""

from __future__ import annotations

from datetime import date

import pytest

from duw.data.loader import load_market_snapshot
from duw.domain.instruments import IRS, NettingSet, SwapDirection
from duw.risk.limits import Limit, check_limit

AS_OF = date(2025, 6, 30)

# Keep runs small but stable for the incremental comparison.
RUN = dict(n_paths=1000, seed=7, n_steps=6)


def _irs(trade_id: str, fixed_rate: float, direction: SwapDirection) -> IRS:
    return IRS(
        trade_id=trade_id,
        counterparty_id="CP001",
        notional=10_000_000.0,
        currency="USD",
        trade_date=AS_OF,
        maturity_date=date(2030, 6, 30),
        fixed_rate=fixed_rate,
        direction=direction,
    )


def _empty_set() -> NettingSet:
    return NettingSet(netting_set_id="NS1", counterparty_id="CP001", trades=())


def test_incremental_on_empty_set_equals_standalone_pfe() -> None:
    snap = load_market_snapshot()
    proposed = _irs("T1", 0.043, SwapDirection.PAY_FIXED)
    result = check_limit(_empty_set(), proposed, snap, limit=5_000_000.0, **RUN)
    # Existing set is empty -> current PFE is exactly 0, so the increment is the
    # whole standalone peak PFE.
    assert result.current_peak_pfe == 0.0
    assert result.incremental_peak_pfe == pytest.approx(result.proposed_peak_pfe)
    assert result.proposed_peak_pfe > 0.0


def test_breach_flagged_when_limit_too_low() -> None:
    snap = load_market_snapshot()
    proposed = _irs("T1", 0.043, SwapDirection.PAY_FIXED)
    # First size the standalone peak PFE with a generous limit.
    sized = check_limit(_empty_set(), proposed, snap, limit=1e12, **RUN)
    tiny_limit = sized.proposed_peak_pfe * 0.5
    breached = check_limit(_empty_set(), proposed, snap, limit=tiny_limit, **RUN)
    assert breached.breach is True
    assert breached.utilization > 1.0
    assert breached.headroom < 0.0


def test_no_breach_when_limit_ample() -> None:
    snap = load_market_snapshot()
    proposed = _irs("T1", 0.043, SwapDirection.PAY_FIXED)
    sized = check_limit(_empty_set(), proposed, snap, limit=1e12, **RUN)
    ample = sized.proposed_peak_pfe * 2.0
    result = check_limit(_empty_set(), proposed, snap, limit=ample, **RUN)
    assert result.breach is False
    assert result.utilization == pytest.approx(0.5, rel=1e-6)
    assert result.headroom > 0.0


def test_headroom_and_utilization_reconcile_to_limit() -> None:
    snap = load_market_snapshot()
    proposed = _irs("T1", 0.043, SwapDirection.PAY_FIXED)
    limit = 4_000_000.0
    result = check_limit(_empty_set(), proposed, snap, limit=limit, **RUN)
    # headroom = limit - proposed; utilization = proposed / limit.
    assert result.headroom == pytest.approx(limit - result.proposed_peak_pfe)
    assert result.utilization == pytest.approx(result.proposed_peak_pfe / limit)
    assert result.headroom + result.proposed_peak_pfe == pytest.approx(limit)


def test_incremental_adds_to_existing_set() -> None:
    snap = load_market_snapshot()
    existing = NettingSet(
        netting_set_id="NS1",
        counterparty_id="CP001",
        trades=(_irs("T1", 0.043, SwapDirection.PAY_FIXED),),
    )
    # A second payer swap adds directional exposure on the same paths.
    proposed = _irs("T2", 0.043, SwapDirection.PAY_FIXED)
    result = check_limit(existing, proposed, snap, limit=1e12, **RUN)
    assert result.current_peak_pfe > 0.0
    assert result.proposed_peak_pfe > result.current_peak_pfe
    assert result.incremental_peak_pfe == pytest.approx(
        result.proposed_peak_pfe - result.current_peak_pfe
    )


def test_offsetting_trade_has_small_incremental() -> None:
    snap = load_market_snapshot()
    existing = NettingSet(
        netting_set_id="NS1",
        counterparty_id="CP001",
        trades=(_irs("T1", 0.043, SwapDirection.PAY_FIXED),),
    )
    # An opposite receiver swap on identical terms nets down the position, so its
    # incremental peak PFE is far below its standalone peak PFE.
    opposite = _irs("T2", 0.043, SwapDirection.RECEIVE_FIXED)
    combined = check_limit(existing, opposite, snap, limit=1e12, **RUN)
    standalone = check_limit(_empty_set(), opposite, snap, limit=1e12, **RUN)
    assert combined.incremental_peak_pfe < standalone.proposed_peak_pfe


def test_limit_dataclass_accepted() -> None:
    snap = load_market_snapshot()
    proposed = _irs("T1", 0.043, SwapDirection.PAY_FIXED)
    limit = Limit(counterparty_id="CP001", amount=4_000_000.0)
    result = check_limit(_empty_set(), proposed, snap, limit=limit, **RUN)
    assert result.limit == 4_000_000.0
