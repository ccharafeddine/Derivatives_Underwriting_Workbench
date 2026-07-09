"""A simple read-only metrics table.

A two-column (metric, value) :class:`QTableWidget` used by the analytics tabs to
show headline numbers next to their chart. These tables always hold a small,
fixed set of rows, so the widget sizes itself to fit every row and never shows a
vertical scrollbar: when the data can fit, it shows in full rather than hiding
rows behind a scroll region.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
)

from duw.glossary import lookup


class MetricsTable(QTableWidget):
    """Read-only ``(metric, value)`` table that grows to fit its rows."""

    def __init__(self) -> None:
        super().__init__(0, 2)
        self.setHorizontalHeaderLabels(["Metric", "Value"])
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        # The row set is small and fixed, so fit content instead of scrolling.
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def set_metrics(self, rows: Sequence[tuple[str, str]]) -> None:
        """Replace the table contents with ``(metric, value)`` rows.

        Each metric cell gets a plain-English tooltip from the glossary when the
        label matches a known term, so the metrics are self-explaining on hover.
        The table is then resized to show every row without scrolling.
        """
        self.setRowCount(len(rows))
        for r, (metric, value) in enumerate(rows):
            metric_item = QTableWidgetItem(str(metric))
            definition = lookup(str(metric))
            if definition is not None:
                metric_item.setToolTip(definition)
            self.setItem(r, 0, metric_item)
            self.setItem(r, 1, QTableWidgetItem(str(value)))
        self.fit_to_contents()

    def fit_to_contents(self) -> None:
        """Pin the table height so every row is visible without a scrollbar.

        Call this after populating the table directly (via ``setRowCount`` /
        ``setItem``) rather than through :meth:`set_metrics`.
        """
        self.resizeRowsToContents()
        header = self.horizontalHeader()
        height = max(header.height(), header.sizeHint().height())
        height += 2 * self.frameWidth()
        for r in range(self.rowCount()):
            height += self.rowHeight(r)
        self.setFixedHeight(height)
