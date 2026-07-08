"""Main window.

The composed :class:`QMainWindow`: a traditional File / Edit / View / Settings
menu bar, a :class:`QTabWidget` of the eight workflow tabs (Trade and
Counterparty are input tabs; Exposure, Limits, Collateral, and CVA are analytics
tabs; Memo and Pipeline remain placeholders), a shared
:class:`~duw.ui.app_state.AppState`, and a Run Analysis action.

Run launches the pipeline on a background :class:`~duw.pipeline.worker.PipelineWorker`
thread so the UI stays responsive; progress is shown on a status-bar progress
bar and results are dispatched to the analytics tabs when the run finishes. All
heavy computation happens on the worker thread. Qt lives here.
"""

from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QTabWidget,
)

from duw.domain.counterparty import Counterparty
from duw.domain.instruments import NettingSet, Trade
from duw.domain.results import AnalysisResults
from duw.pipeline.orchestrator import RunConfig
from duw.pipeline.worker import PipelineWorker, create_worker_thread
from duw.store.deals import Deal, DealStore, default_deal_store_path
from duw.ui.app_state import AppState
from duw.ui.tabs.collateral_tab import CollateralTab
from duw.ui.tabs.counterparty_tab import CounterpartyTab
from duw.ui.tabs.cva_tab import CvaTab
from duw.ui.tabs.exposure_tab import ExposureTab
from duw.ui.tabs.limits_tab import LimitsTab
from duw.ui.tabs.memo_tab import MemoTab
from duw.ui.tabs.pipeline_tab import PipelineTab
from duw.ui.tabs.trade_tab import TradeTab

# The eight workflow tabs, in the order a run flows through them.
TAB_NAMES: tuple[str, ...] = (
    "Trade",
    "Counterparty",
    "Exposure",
    "Limits",
    "Collateral",
    "CVA",
    "Memo",
    "Pipeline",
)

# Monte Carlo settings for a UI-triggered run (made configurable in a later
# session); modest enough to stay responsive with the progress bar.
_RUN_PATHS = 2000
_RUN_STEPS = 12


class MainWindow(QMainWindow):
    """Top-level window: menu bar, tabbed workflow, and the run wiring."""

    def __init__(
        self, app_state: AppState | None = None, store: DealStore | None = None
    ) -> None:
        super().__init__()
        self.setWindowTitle("Derivatives Underwriting Workbench")
        self.resize(1200, 800)

        self.app_state = app_state or AppState()
        self.store = store or DealStore(default_deal_store_path())
        self._worker: PipelineWorker | None = None
        self._thread = None
        self.results: AnalysisResults | None = None

        self.trade_tab = TradeTab(self.app_state)
        self.counterparty_tab = CounterpartyTab(self.app_state)
        self.exposure_tab = ExposureTab()
        self.limits_tab = LimitsTab()
        self.collateral_tab = CollateralTab()
        self.cva_tab = CvaTab()
        self.memo_tab = MemoTab()
        self.pipeline_tab = PipelineTab(self.store)
        self.pipeline_tab.reopenRequested.connect(self._on_reopen)

        self._build_tabs()
        self._build_menu_bar()
        self._build_status_bar()

        self.app_state.tradeChanged.connect(self._update_run_enabled)
        self.app_state.counterpartyChanged.connect(self._update_run_enabled)
        self._update_run_enabled()

    # -- construction ------------------------------------------------------ #
    def _build_tabs(self) -> None:
        self.tabs = QTabWidget()
        self.tabs.addTab(self.trade_tab, "Trade")
        self.tabs.addTab(self.counterparty_tab, "Counterparty")
        self.tabs.addTab(self.exposure_tab, "Exposure")
        self.tabs.addTab(self.limits_tab, "Limits")
        self.tabs.addTab(self.collateral_tab, "Collateral")
        self.tabs.addTab(self.cva_tab, "CVA")
        self.tabs.addTab(self.memo_tab, "Memo")
        self.tabs.addTab(self.pipeline_tab, "Pipeline")
        self.setCentralWidget(self.tabs)

    def _build_menu_bar(self) -> None:
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")
        self.run_action = QAction("&Run Analysis", self)
        self.run_action.setShortcut("Ctrl+R")
        self.run_action.triggered.connect(self._on_run)
        file_menu.addAction(self.run_action)
        self.save_deal_action = QAction("&Save Deal…", self)
        self.save_deal_action.setShortcut("Ctrl+S")
        self.save_deal_action.setEnabled(False)
        self.save_deal_action.triggered.connect(self._on_save_deal)
        file_menu.addAction(self.save_deal_action)
        file_menu.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        menu_bar.addMenu("&Edit")
        menu_bar.addMenu("&View")
        menu_bar.addMenu("&Settings")

    def _build_status_bar(self) -> None:
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setMaximumWidth(220)
        self.progress.setVisible(False)
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().showMessage("Enter a trade and counterparty to run.")

    # -- run enable/disable ------------------------------------------------ #
    def _update_run_enabled(self, *_args: object) -> None:
        running = self._thread is not None
        ready = self.app_state.is_ready() and not running
        self.run_action.setEnabled(ready)
        if running:
            return
        if self.app_state.is_ready():
            self.statusBar().showMessage("Ready to run.")
        else:
            self.statusBar().showMessage("Enter a valid trade and counterparty to run.")

    # -- run lifecycle ----------------------------------------------------- #
    def _on_run(self) -> None:
        if not self.app_state.is_ready() or self._thread is not None:
            return
        counterparty, existing_set, trade = self.app_state.run_inputs()
        config = RunConfig(n_paths=_RUN_PATHS, n_steps=_RUN_STEPS)
        self._start_run(counterparty, existing_set, trade, config)

    def _on_reopen(self, deal: Deal) -> None:
        """Re-run a saved deal to repopulate the analytics tabs."""
        if self._thread is not None:
            return
        counterparty, existing_set, trade, config = deal.to_run_inputs()
        self.statusBar().showMessage(f"Reopening deal: {deal.name}…")
        self._start_run(counterparty, existing_set, trade, config)

    def _start_run(
        self,
        counterparty: Counterparty,
        existing_set: NettingSet,
        trade: Trade,
        config: RunConfig,
    ) -> None:
        self._worker = PipelineWorker(counterparty, existing_set, trade, config)
        self._thread = create_worker_thread(self._worker)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._thread.finished.connect(self._on_thread_finished)

        self.run_action.setEnabled(False)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.statusBar().showMessage("Running analysis…")
        self._thread.start()

    def _on_progress(self, fraction: float, message: str) -> None:
        self.progress.setValue(int(fraction * 100))
        self.statusBar().showMessage(message)

    def _on_finished(self, results: AnalysisResults) -> None:
        self.results = results
        self.exposure_tab.set_results(results)
        self.limits_tab.set_results(results)
        self.collateral_tab.set_results(results)
        self.cva_tab.set_results(results)
        self.memo_tab.set_results(results)
        self.save_deal_action.setEnabled(True)
        self.tabs.setCurrentWidget(self.exposure_tab)
        self.statusBar().showMessage("Analysis complete.")

    def _on_failed(self, message: str) -> None:
        QMessageBox.critical(self, "Analysis failed", message)
        self.statusBar().showMessage("Analysis failed.")

    def _on_thread_finished(self) -> None:
        self.progress.setVisible(False)
        self._thread = None
        self._worker = None
        self._update_run_enabled()

    # -- deal persistence -------------------------------------------------- #
    def _default_deal_name(self) -> str:
        results = self.results
        if results is not None and results.counterparty is not None:
            product = ""
            if results.netting_set is not None and results.netting_set.trades:
                product = results.netting_set.trades[-1].product
            return f"{results.counterparty.name} — {product}".strip(" —")
        return "Deal"

    def _on_save_deal(self) -> None:
        if self.results is None:
            return
        name, ok = QInputDialog.getText(
            self, "Save Deal", "Deal name:", text=self._default_deal_name()
        )
        if not ok or not name.strip():
            return
        try:
            deal = Deal.from_results(name.strip(), self.results)
        except ValueError as exc:
            QMessageBox.warning(self, "Cannot save deal", str(exc))
            return
        self.pipeline_tab.add_deal(deal)
        self.statusBar().showMessage(f"Saved deal: {deal.name}")
