"""Learn-mode tests (v2): glossary, tooltips, and example deals."""

from __future__ import annotations

from duw.domain.instruments import CDS, IRS, FXForward
from duw.examples import examples
from duw.glossary import GLOSSARY, lookup


# --------------------------------------------------------------------------- #
# Glossary (Qt-free)
# --------------------------------------------------------------------------- #
def test_glossary_has_core_terms() -> None:
    for term in ("PFE", "CVA", "CSA", "MPoR", "Merton", "Utilization"):
        assert term in GLOSSARY
        assert len(GLOSSARY[term]) > 20


def test_lookup_prefers_longest_match() -> None:
    # "Peak PFE (95%)" should resolve to the Peak-PFE definition, not plain PFE.
    assert lookup("Peak PFE (95%)") == GLOSSARY["Peak PFE"]
    assert lookup("Max PFE (99%)") == GLOSSARY["PFE"]
    assert lookup("CVA") == GLOSSARY["CVA"]
    assert lookup("Utilization") == GLOSSARY["Utilization"]


def test_lookup_unknown_is_none() -> None:
    assert lookup("Grid dates") is None


# --------------------------------------------------------------------------- #
# Example deals (Qt-free)
# --------------------------------------------------------------------------- #
def test_examples_are_well_formed() -> None:
    exs = examples()
    assert len(exs) >= 4
    ids = {"CP001", "CP002", "CP003", "CP004"}
    for ex in exs:
        assert ex.name and ex.description
        assert ex.counterparty_id in ids
        assert isinstance(ex.trade, (IRS, FXForward, CDS))
    # The netted-book example carries a book; the breaching one is large.
    by_name = {ex.name: ex for ex in exs}
    assert len(by_name["Netted book (offsetting trade)"].book) == 1
    assert by_name["Limit-breaching swap"].trade.notional >= 100_000_000.0


# --------------------------------------------------------------------------- #
# Tooltips and glossary dialog (offscreen Qt)
# --------------------------------------------------------------------------- #
def test_metrics_table_sets_glossary_tooltips(qapp) -> None:
    from duw.ui.widgets.result_table import MetricsTable

    table = MetricsTable()
    table.set_metrics([("Peak PFE (95%)", "600,000"), ("Grid dates", "11")])
    assert table.item(0, 0).toolTip() == GLOSSARY["Peak PFE"]
    assert table.item(1, 0).toolTip() == ""  # unknown metric -> no tooltip


def test_glossary_dialog_lists_all_terms(qapp) -> None:
    from PySide6.QtWidgets import QTableWidget

    from duw.ui.dialogs import build_glossary_dialog

    dialog = build_glossary_dialog()
    table = dialog.findChild(QTableWidget)
    assert table is not None
    assert table.rowCount() == len(GLOSSARY)


# --------------------------------------------------------------------------- #
# Loading examples into the main window (offscreen Qt)
# --------------------------------------------------------------------------- #
def test_load_example_populates_inputs(qapp) -> None:
    from duw.ui.main_window import MainWindow

    window = MainWindow()
    by_name = {ex.name: ex for ex in examples()}
    window._load_example(by_name["Netted book (offsetting trade)"])

    state = window.app_state
    assert state.counterparty is not None
    assert state.counterparty.counterparty_id == "CP001"
    assert state.trade is not None
    # The proposed trade is the receiver; the book holds the offsetting payer.
    assert len(state.book) == 1
    assert state.is_ready()
    _, existing, proposed = state.run_inputs()
    assert len(existing.trades) == 1


def test_load_cds_example_sets_product(qapp) -> None:
    from duw.ui.main_window import MainWindow

    window = MainWindow()
    by_name = {ex.name: ex for ex in examples()}
    window._load_example(by_name["Distressed-name CDS protection"])
    trade = window.app_state.trade
    assert isinstance(trade, CDS)
    assert trade.reference_entity == "INITECH"
    assert window.app_state.counterparty.counterparty_id == "CP003"
