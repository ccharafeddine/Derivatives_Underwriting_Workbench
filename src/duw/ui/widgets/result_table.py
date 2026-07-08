"""A simple read-only metrics table.

A two-column (metric, value) :class:`QTableWidget` used by the analytics tabs to
show headline numbers next to their chart.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
)

from duw.glossary import lookup


class MetricsTable(QTableWidget):
    """Read-only ``(metric, value)`` table."""

    def __init__(self) -> None:
        super().__init__(0, 2)
        self.setHorizontalHeaderLabels(["Metric", "Value"])
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)

    def set_metrics(self, rows: Sequence[tuple[str, str]]) -> None:
        """Replace the table contents with ``(metric, value)`` rows.

        Each metric cell gets a plain-English tooltip from the glossary when the
        label matches a known term, so the metrics are self-explaining on hover.
        """
        self.setRowCount(len(rows))
        for r, (metric, value) in enumerate(rows):
            metric_item = QTableWidgetItem(str(metric))
            definition = lookup(str(metric))
            if definition is not None:
                metric_item.setToolTip(definition)
            self.setItem(r, 0, metric_item)
            self.setItem(r, 1, QTableWidgetItem(str(value)))
