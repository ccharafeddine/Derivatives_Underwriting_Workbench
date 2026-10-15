"""Phase 3 review fixes: MPoR gap risk on coarse grids, trade validation,
print-styled memo charts, scrollable pages."""

from __future__ import annotations

import datetime as dt
from dataclasses import replace

import numpy as np
import pytest

from duw.examples import examples
from duw.risk.collateral import CSA, _lagged_values, apply_csa


def _brownian_cube(grid: np.ndarray, n: int = 40_000, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    dw = rng.standard_normal((n, len(grid) - 1)) * np.sqrt(np.diff(grid))
    return np.concatenate([np.zeros((n, 1)), np.cumsum(dw, axis=1)], axis=1)


def test_mpor_gap_risk_does_not_vanish_on_a_coarse_grid() -> None:
    # Reference: a grid whose step equals the MPoR, so every lag date is a
    # simulated date and the collateralized EE is exact (up to MC noise).
    d = 10 / 252
    csa = CSA(threshold=0.0, mta=0.0, initial_margin=0.0, mpor_days=10)
    fine = np.arange(0, 51) * d
    ref = apply_csa(_brownian_cube(fine, seed=2), tuple(fine), csa).mean(axis=0)
    coarse = np.linspace(0.0, fine[-1], 9)
    cube = _brownian_cube(coarse)
    got = apply_csa(cube, tuple(coarse), csa).mean(axis=0)[2:]
    want = np.interp(coarse[2:], fine, ref)
    assert np.allclose(got, want, rtol=0.08), (got, want)
    # Plain linear interpolation (the old behaviour) understates it badly.
    lag = _lagged_values(cube, tuple(coarse), d, bridge=False)
    old = np.maximum(np.maximum(cube, 0) - np.maximum(lag, 0), 0).mean(axis=0)[2:]
    assert old.mean() < 0.6 * want.mean()


def test_lag_on_a_grid_date_is_exact_and_reproducible() -> None:
    grid = np.linspace(0.0, 1.0, 26)  # step 0.04 = exactly 10/250... close
    cube = _brownian_cube(grid, n=500)
    step = grid[1]
    lag = _lagged_values(cube, tuple(grid), step)
    assert np.allclose(lag[:, 5], cube[:, 4])
    again = _lagged_values(cube, tuple(grid), 0.013)
    assert np.array_equal(again, _lagged_values(cube, tuple(grid), 0.013))


@pytest.mark.parametrize(
    "change",
    [
        {"notional": 0.0},
        {"notional": float("nan")},
        {"maturity_date": dt.date(2025, 6, 30)},
        {"fixed_rate": float("inf")},
    ],
)
def test_invalid_trades_are_rejected(change) -> None:
    with pytest.raises(ValueError, match="Trade EX-IRS"):
        replace(examples()[0].trade, **change)


def test_cds_recovery_must_be_below_one() -> None:
    cds = examples()[1].trade
    with pytest.raises(ValueError, match="recovery"):
        replace(cds, recovery_rate=1.0)


def test_memo_charts_use_print_palette() -> None:
    from duw.reports.memo import _figures
    from duw.ui.widgets.charts import exposure_figure
    from tests.test_graphite_shell import _results

    figs = dict(_figures(_results()))
    fig = figs["Exposure"]
    assert fig.layout.paper_bgcolor == "#FFFFFF"
    assert {t.line.color for t in fig.data if t.name == "EE"} == {"#1F2328"}
    assert exposure_figure(None) is not None


def test_pages_scroll_instead_of_forcing_a_tall_window(qapp) -> None:
    from duw.ui.main_window import MainWindow

    window = MainWindow()
    assert window.page_scroll.widget() is window.tabs
    assert window.minimumSizeHint().height() < 700
    assert window.minimumSizeHint().width() <= 1366


def test_trade_tab_shows_domain_validation_errors(qapp, monkeypatch) -> None:
    from duw.ui.tabs.trade_tab import TradeTab

    tab = TradeTab()

    def boom():
        raise ValueError("Trade T1: spread must be non-negative")

    monkeypatch.setattr(tab, "_build", boom)
    tab._refresh()
    assert "spread must be non-negative" in tab.status.text()
    assert not tab.add_book_btn.isEnabled()
