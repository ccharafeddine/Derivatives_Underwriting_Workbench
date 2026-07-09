"""Shared right-hand panel for the analytics tabs.

Pairs a chart with a companion panel: the headline metrics on top and a
plain-English reading of them below. Keeping this in one place lets the chart
take the width while the panel is filled with useful content rather than empty
space, consistently across the Exposure, CVA, and Limits tabs.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGroupBox, QLabel, QVBoxLayout, QWidget

from duw.ui.widgets.result_table import MetricsTable


def side_panel(table: MetricsTable, commentary: QLabel) -> QWidget:
    """Build the ``[key numbers] + [what this means]`` companion panel."""
    commentary.setWordWrap(True)
    commentary.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(QLabel("<b>Key numbers</b>"))
    layout.addWidget(table)
    box = QGroupBox("What this means")
    box_layout = QVBoxLayout(box)
    box_layout.addWidget(commentary)
    box_layout.addStretch(1)
    layout.addWidget(box, 1)
    return panel
