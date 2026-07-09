"""MetricsTable sizing. Headless via offscreen Qt.

The metrics tables hold a small, fixed set of rows and must show them all
without a vertical scrollbar, so they fit their height to their content and grow
as rows are added.
"""

from __future__ import annotations

from PySide6.QtCore import Qt

from duw.ui.widgets.result_table import MetricsTable


def test_table_fits_its_rows_without_scrolling(qapp) -> None:
    table = MetricsTable()
    table.set_metrics([("A", "1"), ("B", "2"), ("C", "3")])
    # Fixed height (min == max) so surrounding layouts cannot squeeze or stretch
    # it away from its content.
    assert table.minimumHeight() == table.maximumHeight()
    assert table.minimumHeight() > 0
    # The vertical scrollbar is off — every row shows.
    assert table.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff


def test_table_grows_with_more_rows(qapp) -> None:
    table = MetricsTable()
    table.set_metrics([("A", "1")])
    small = table.maximumHeight()
    table.set_metrics([("A", "1"), ("B", "2"), ("C", "3"), ("D", "4")])
    assert table.maximumHeight() > small


def test_fit_to_contents_handles_direct_population(qapp) -> None:
    from PySide6.QtWidgets import QTableWidgetItem

    table = MetricsTable()
    table.setRowCount(2)
    table.setItem(0, 0, QTableWidgetItem("x"))
    table.setItem(1, 0, QTableWidgetItem("y"))
    table.fit_to_contents()
    assert table.minimumHeight() == table.maximumHeight() > 0
