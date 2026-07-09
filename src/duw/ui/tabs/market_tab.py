"""Market data editor tab.

Shows the working market snapshot — zero curves by currency, FX spots, and CDS
spread curves by issuer — and lets the user edit the values to test their own
market. Applying rebuilds a :class:`MarketSnapshot` and sets it on the shared
:class:`~duw.ui.app_state.AppState`, so the next analysis prices against it.
Tenors and recovery/vol assumptions are held fixed; only rates, spots, and
spreads are editable. Qt lives here.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from duw.domain.market import CreditCurve, MarketSnapshot, YieldCurve
from duw.ui.app_state import AppState
from duw.ui.widgets.charts import credit_curves_figure, yield_curves_figure
from duw.ui.widgets.plotly_view import PlotlyView

_ROW_H = 26


def _value_table(
    headers: tuple[str, str], rows: list[tuple[str, float]]
) -> QTableWidget:
    table = QTableWidget(len(rows), 2)
    table.setHorizontalHeaderLabels(list(headers))
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(_ROW_H)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    for r, (label, value) in enumerate(rows):
        left = QTableWidgetItem(label)
        left.setFlags(left.flags() & ~Qt.ItemFlag.ItemIsEditable)
        table.setItem(r, 0, left)
        table.setItem(r, 1, QTableWidgetItem(f"{value:g}"))
    table.resizeColumnsToContents()
    # Size to fit all rows so only the outer scroll area scrolls.
    table.setFixedHeight(30 + _ROW_H * len(rows) + 2)
    return table


def _read_column(table: QTableWidget) -> list[float]:
    values: list[float] = []
    for r in range(table.rowCount()):
        item = table.item(r, 1)
        try:
            values.append(float(item.text()))
        except (TypeError, ValueError):
            values.append(0.0)
    return values


class MarketTab(QWidget):
    """Editable view of the working market snapshot."""

    def __init__(self, app_state: AppState) -> None:
        super().__init__()
        self._app_state = app_state
        self._rate_tables: dict[str, QTableWidget] = {}
        self._credit_tables: dict[str, QTableWidget] = {}
        self._fx_table: QTableWidget | None = None

        self._body = QVBoxLayout()
        container = QWidget()
        container.setLayout(self._body)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)

        controls = QHBoxLayout()
        self.apply_btn = QPushButton("Apply to market")
        self.reset_btn = QPushButton("Reset to bundled")
        self.apply_btn.clicked.connect(self._apply)
        self.reset_btn.clicked.connect(self._app_state.reset_snapshot)
        self.status = QLabel("Edit rates (%), FX spots, and spreads (bps), then Apply.")
        controls.addWidget(self.apply_btn)
        controls.addWidget(self.reset_btn)
        controls.addWidget(self.status)
        controls.addStretch(1)

        # Plotted curves on top, the editable number tables below. The two views
        # are created once and only their figures are refreshed on rebuild.
        self.yield_view = PlotlyView()
        self.credit_view = PlotlyView()
        charts_widget = QWidget()
        charts_row = QHBoxLayout(charts_widget)
        charts_row.setContentsMargins(0, 0, 0, 0)
        charts_row.addWidget(self.yield_view)
        charts_row.addWidget(self.credit_view)

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(charts_widget)
        split.addWidget(scroll)
        split.setSizes([300, 320])

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(split)

        self._app_state.snapshotChanged.connect(self._rebuild)
        self._rebuild()

    # -- build from snapshot ----------------------------------------------- #
    def _rebuild(self) -> None:
        while self._body.count():
            item = self._body.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rate_tables.clear()
        self._credit_tables.clear()
        snap = self._app_state.snapshot

        # Two columns side by side — rates + FX on the left, credit on the right —
        # so the editable tables fit on screen without a long vertical scroll.
        columns = QWidget()
        cols = QHBoxLayout(columns)
        cols.setContentsMargins(0, 0, 0, 0)

        left = QVBoxLayout()
        left.addWidget(QLabel("<b>Zero curves</b> (rate in %)"))
        for ccy, curve in snap.discount_curves.items():
            box = QGroupBox(f"{ccy} curve")
            v = QVBoxLayout(box)
            table = _value_table(
                ("Tenor (y)", "Zero rate %"),
                [
                    (f"{t:g}", r * 100.0)
                    for t, r in zip(curve.tenors, curve.zero_rates, strict=True)
                ],
            )
            self._rate_tables[ccy] = table
            v.addWidget(table)
            left.addWidget(box)
        left.addWidget(QLabel("<b>FX spot</b>"))
        self._fx_table = _value_table(
            ("Pair", "Spot"), [(pair, rate) for pair, rate in snap.fx_spot.items()]
        )
        left.addWidget(self._fx_table)
        left.addStretch(1)

        right = QVBoxLayout()
        right.addWidget(QLabel("<b>Credit spreads</b> (bps)"))
        for issuer, curve in snap.credit_curves.items():
            box = QGroupBox(f"{issuer} spreads")
            v = QVBoxLayout(box)
            table = _value_table(
                ("Tenor (y)", "Spread bps"),
                [
                    (f"{t:g}", s * 1e4)
                    for t, s in zip(curve.tenors, curve.spreads, strict=True)
                ],
            )
            self._credit_tables[issuer] = table
            v.addWidget(table)
            right.addWidget(box)
        right.addStretch(1)

        cols.addLayout(left)
        cols.addLayout(right)
        self._body.addWidget(columns)
        self._body.addStretch(1)

        # Refresh the plotted curves to match the (possibly edited) snapshot.
        self.yield_view.set_figure(yield_curves_figure(snap))
        self.credit_view.set_figure(credit_curves_figure(snap))

    # -- apply edits ------------------------------------------------------- #
    def _apply(self) -> None:
        snap = self._app_state.snapshot
        discount_curves = {}
        for ccy, curve in snap.discount_curves.items():
            rates = [v / 100.0 for v in _read_column(self._rate_tables[ccy])]
            discount_curves[ccy] = YieldCurve(
                currency=curve.currency, tenors=curve.tenors, zero_rates=tuple(rates)
            )
        fx_values = _read_column(self._fx_table) if self._fx_table else []
        fx_spot = {pair: fx_values[i] for i, pair in enumerate(snap.fx_spot)}
        credit_curves = {}
        for issuer, curve in snap.credit_curves.items():
            spreads = [
                max(v / 1e4, 1e-6) for v in _read_column(self._credit_tables[issuer])
            ]
            credit_curves[issuer] = CreditCurve(
                issuer=curve.issuer,
                tenors=curve.tenors,
                spreads=tuple(spreads),
                recovery_rate=curve.recovery_rate,
            )
        new_snapshot = MarketSnapshot(
            as_of=snap.as_of,
            discount_curves=discount_curves,
            fx_spot=fx_spot,
            credit_curves=credit_curves,
            rate_vols=dict(snap.rate_vols),
            fx_vols=dict(snap.fx_vols),
        )
        self._app_state.set_snapshot(new_snapshot)
        self.status.setText("Applied — the next analysis prices against these values.")
