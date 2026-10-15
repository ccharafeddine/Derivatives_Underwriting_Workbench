"""Deal overview: the underwriting decision on one page.

Exposure profile of the netting set including the proposed trade, the
counterparty's credit read-out, the limit check, the (illustrative) decision
with its rationale, and the netting set's trades with today's mark-to-market.
Everything here is derived from the last :class:`AnalysisResults`; the module
also owns :func:`deal_kpis`, the numbers the persistent KPI strip shows.
"""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from duw.domain.results import AnalysisResults
from duw.reports.interpreter import interpret_exposure, recommend
from duw.ui import theme
from duw.ui.format import full_money, pct, short_money, tone
from duw.ui.widgets.app_shell import LimitBar, Panel
from duw.ui.widgets.charts import exposure_figure
from duw.ui.widgets.plotly_view import PlotlyView

_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
_LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter


def verdict_tone(verdict: str | None) -> str | None:
    """KPI tone for a recommendation: approve / conditions / decline."""
    if not verdict:
        return None
    v = verdict.lower()
    if v.startswith("decline"):
        return "neg"
    if "condition" in v:
        return "warn"
    return "pos"


def mtm_today(results: AnalysisResults) -> float:
    """Net mark-to-market today (every path shares the t = 0 value)."""
    cube = results.net_mtm_cube
    if cube is None:
        return math.nan
    arr = np.asarray(cube, dtype=float)
    if arr.ndim != 2 or arr.shape[1] == 0:
        return math.nan
    return float(arr[:, 0].mean())


def deal_kpis(
    results: AnalysisResults | None,
) -> list[tuple[str, str, str, str | None]]:
    """``(name, value, sub, tone)`` for each KPI strip cell."""
    if results is None:
        return []
    rows: list[tuple[str, str, str, str | None]] = []
    exp, lim, cva = results.exposure, results.limits, results.cva
    if exp is not None:
        sub = "" if math.isnan(exp.peak_pfe_time) else f"at {exp.peak_pfe_time:.1f}y"
        if lim is not None and not math.isnan(lim.limit):
            sub += f" · limit {short_money(lim.limit)}"
        rows.append(("Peak PFE 95%", short_money(exp.peak_pfe), sub.strip(" ·"), None))
        rows.append(("EPE", short_money(exp.epe), "expected positive exposure", None))
    if lim is not None:
        t = "neg" if lim.breach else ("warn" if lim.utilization > 0.85 else None)
        rows.append(
            (
                "Limit use",
                pct(lim.utilization),
                f"headroom {short_money(lim.headroom)}",
                t,
            )
        )
    if cva is not None:
        lgd = "" if math.isnan(cva.lgd) else f"LGD {cva.lgd:.0%}"
        rows.append(("CVA", full_money(-cva.cva, signed=True), lgd, tone(-cva.cva)))
        rows.append(
            ("DVA", full_money(cva.dva, signed=True), "own credit", tone(cva.dva))
        )
        rows.append(
            ("FVA", full_money(-cva.fva, signed=True), "funding", tone(-cva.fva))
        )
    mtm = mtm_today(results)
    if not math.isnan(mtm):
        rows.append(
            ("MtM today", full_money(mtm, signed=True), "net, netting set", tone(mtm))
        )
    if exp is not None or lim is not None:
        rec = recommend(results)
        rows.append(
            ("Recommendation", rec.verdict, "illustrative", verdict_tone(rec.verdict))
        )
    return rows


def _item(text: str, align=_LEFT, color: str | None = None, bold: bool = False):
    item = QTableWidgetItem(text)
    item.setTextAlignment(align)
    if color:
        item.setForeground(QColor(color))
    if bold:
        font = QFont(item.font())
        font.setWeight(QFont.Weight.DemiBold)
        item.setFont(font)
    return item


class OverviewTab(QWidget):
    """Deal overview page."""

    TRADE_COLUMNS = ("Trade", "Product", "CCY", "Notional", "Maturity", "MtM")

    def __init__(self) -> None:
        super().__init__()
        self.results: AnalysisResults | None = None

        # Left: exposure chart + netting set.
        self.exposure_panel = Panel(
            "Exposure profile", "netting set incl. proposed trade"
        )
        self.view = PlotlyView()
        self.view.setMinimumHeight(300)
        self.view.set_message("Run an analysis to see the exposure profile.")
        self.exposure_panel.add(self.view, 1)

        self.book_panel = Panel("Netting set")
        self.trades = QTableWidget(0, len(self.TRADE_COLUMNS))
        self.trades.setHorizontalHeaderLabels(list(self.TRADE_COLUMNS))
        self.trades.verticalHeader().setVisible(False)
        self.trades.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.trades.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.trades.setShowGrid(False)
        self.trades.setFrameShape(QTableWidget.Shape.NoFrame)
        header = self.trades.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setDefaultAlignment(_LEFT)
        self.trades.verticalHeader().setDefaultSectionSize(26)
        self.trades.setMaximumHeight(190)
        self.book_panel.add(self.trades)

        left = QVBoxLayout()
        left.setSpacing(12)
        left.addWidget(self.exposure_panel, 1)
        left.addWidget(self.book_panel)

        # Right: counterparty, limit check, decision.
        self.cp_panel = Panel("Counterparty")
        cp_body = QWidget()
        self.cp_grid = QGridLayout(cp_body)
        self.cp_grid.setContentsMargins(12, 8, 12, 10)
        self.cp_grid.setHorizontalSpacing(12)
        self.cp_grid.setVerticalSpacing(5)
        self.cp_panel.add(cp_body)

        self.limit_panel = Panel("Limit check", "PFE 95%")
        lim_body = QWidget()
        lim_lay = QVBoxLayout(lim_body)
        lim_lay.setContentsMargins(12, 10, 12, 10)
        lim_lay.setSpacing(4)
        self.limit_bar = LimitBar()
        self.limit_text = QLabel("Run an analysis to check the limit.")
        self.limit_text.setObjectName("muted")
        self.limit_text.setWordWrap(True)
        lim_lay.addWidget(self.limit_bar)
        lim_lay.addWidget(self.limit_text)
        self.limit_panel.add(lim_body)

        self.decision_panel = Panel("Decision", "illustrative · not credit advice")
        dec_body = QWidget()
        dec_lay = QVBoxLayout(dec_body)
        dec_lay.setContentsMargins(12, 10, 12, 12)
        dec_lay.setSpacing(6)
        self.verdict = QLabel("—")
        self.verdict.setObjectName("kpiValue")
        self.rationale = QLabel("Run an analysis to draft the underwriting decision.")
        self.rationale.setObjectName("muted")
        self.rationale.setWordWrap(True)
        dec_lay.addWidget(self.verdict)
        dec_lay.addWidget(self.rationale)
        self.decision_panel.add(dec_body)

        right_w = QWidget()
        right_w.setFixedWidth(330)
        right = QVBoxLayout(right_w)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(12)
        right.addWidget(self.cp_panel)
        right.addWidget(self.limit_panel)
        right.addWidget(self.decision_panel)
        right.addStretch(1)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        row.addLayout(left, 1)
        row.addWidget(right_w)
        self._set_cp_rows([("Counterparty", "—")])

    # ------------------------------------------------------------------ #
    def _set_cp_rows(self, rows: list[tuple[str, str]]) -> None:
        while self.cp_grid.count():
            w = self.cp_grid.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for r, (k, v) in enumerate(rows):
            key = QLabel(k)
            key.setObjectName("muted")
            val = QLabel(v)
            val.setAlignment(_RIGHT)
            self.cp_grid.addWidget(key, r, 0)
            self.cp_grid.addWidget(val, r, 1)

    def counterparty_rows(self, results: AnalysisResults) -> list[tuple[str, str]]:
        cp, prof = results.counterparty, results.credit_profile
        rows: list[tuple[str, str]] = []
        if cp is not None:
            rows.append(("Name", cp.name))
            rows.append(("Sector", cp.sector))
        if prof is not None:
            if prof.internal_grade:
                rows.append(("Internal rating", str(prof.internal_grade)))
            if prof.merton_pd is not None:
                rows.append(("Merton 1y PD", f"{prof.merton_pd:.2%}"))
            if prof.distance_to_default is not None:
                rows.append(("Distance to default", f"{prof.distance_to_default:.2f}σ"))
            if prof.altman_z is not None:
                rows.append(("Altman Z″", f"{prof.altman_z:.2f} ({prof.altman_zone})"))
        snap = results.snapshot
        if cp is not None and cp.cds_issuer and snap is not None:
            try:
                curve = snap.credit(cp.cds_issuer)
                s5 = float(np.interp(5.0, curve.tenors, curve.spreads)) * 1e4
                rows.append(
                    ("CDS 5y / recovery", f"{s5:.0f} bp / {curve.recovery_rate:.0%}")
                )
            except (KeyError, ValueError):
                pass
        return rows or [("Counterparty", "—")]

    def set_results(self, results: AnalysisResults) -> None:
        self.results = results
        fig = exposure_figure(results.exposure)
        if results.exposure is not None and results.exposure.time_grid:
            # The panel title already names the chart.
            fig.update_layout(title=None, margin=dict(t=16))
        self.view.set_figure(fig)
        self.exposure_panel.set_note(
            interpret_exposure(results) if results.exposure else ""
        )
        self._set_cp_rows(self.counterparty_rows(results))
        cp = results.counterparty
        self.cp_panel.set_aside(cp.name if cp is not None else "")
        self._set_limits(results)
        self._set_decision(results)
        self._set_trades(results)

    def _set_limits(self, results: AnalysisResults) -> None:
        lim = results.limits
        if lim is None or math.isnan(lim.proposed_peak_pfe):
            self.limit_bar.set_values(0, 0, 0)
            self.limit_text.setText("No limit check for this run.")
            return
        self.limit_bar.set_values(
            lim.current_peak_pfe, lim.incremental_peak_pfe, lim.limit
        )
        self.limit_text.setText(
            f"Existing {short_money(lim.current_peak_pfe)} · proposed "
            f"{short_money(lim.incremental_peak_pfe, signed=True)}"
            f" · limit {short_money(lim.limit)}"
            f" · {pct(lim.utilization)} used" + (" · BREACH" if lim.breach else "")
        )

    def _set_decision(self, results: AnalysisResults) -> None:
        rec = recommend(results)
        t = theme.tokens()
        color = {"pos": t["green"], "neg": t["red"], "warn": t["amber"]}.get(
            verdict_tone(rec.verdict) or "", t["text"]
        )
        self.verdict.setText(rec.verdict)
        self.verdict.setStyleSheet(f"color: {color};")
        self.rationale.setText(rec.rationale)

    def _set_trades(self, results: AnalysisResults) -> None:
        ns = results.netting_set
        trades = list(ns.trades) if ns is not None else []
        mtms: dict[str, float] = {}
        if ns is not None and results.snapshot is not None and trades:
            try:
                from duw.risk.exposure import ExposureEngine

                engine = ExposureEngine(ns, results.snapshot)
                mtms = {t.trade_id: m for t, m in engine.inception_mtms()}
            except Exception:  # noqa: BLE001 - the table degrades to "—"
                mtms = {}
        t = theme.tokens()
        self.trades.setRowCount(len(trades))
        for r, trade in enumerate(trades):
            proposed = r == len(trades) - 1
            mtm = mtms.get(trade.trade_id, math.nan)
            mtm_color = (
                t["green"]
                if tone(mtm) == "pos"
                else t["red"]
                if tone(mtm) == "neg"
                else None
            )
            label = "NEW" if proposed else trade.trade_id
            cells = [
                _item(label, bold=True, color=t["accent_soft"] if proposed else None),
                _item(trade.product),
                _item(trade.currency),
                _item(short_money(trade.notional), _RIGHT),
                _item(f"{trade.maturity_date:%Y-%m}", _RIGHT),
                _item(full_money(mtm, signed=True), _RIGHT, mtm_color),
            ]
            for c, item in enumerate(cells):
                self.trades.setItem(r, c, item)
        for c in range(3, len(self.TRADE_COLUMNS)):
            self.trades.horizontalHeaderItem(c).setTextAlignment(_RIGHT)
        n = len(trades)
        net = sum(v for v in mtms.values() if not math.isnan(v)) if mtms else math.nan
        ns_id = ns.netting_set_id if ns is not None else ""
        self.book_panel.title_label.setText(f"NETTING SET {ns_id}".strip())
        self.book_panel.set_aside(
            f"{n} trade{'s' if n != 1 else ''} · net MtM {full_money(net, signed=True)}"
        )
