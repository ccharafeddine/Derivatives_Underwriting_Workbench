"""Main window.

The composed :class:`QMainWindow` in the Graphite layout: a persistent deal
header (top bar with the deal in context and the main actions), grouped left
navigation, and for each page a title, the deal's KPI strip and the page
itself. Pages: the deal Overview (decision), the inputs (Trade, Counterparty,
Market), the analytics (Exposure, Limits, Collateral, CVA, Scenario,
Sensitivities) and the outputs (Memo, Pipeline, Simulator), all over a shared
:class:`~duw.ui.app_state.AppState`. The pages live in a :class:`QTabWidget`
whose tab bar is hidden (the navigation drives it), so ``window.tabs`` keeps
its familiar API. The File / View / Settings / Help menu bar is kept.

Run launches the pipeline on a background :class:`~duw.pipeline.worker.PipelineWorker`
thread so the UI stays responsive; progress is shown on a status-bar progress
bar and results are dispatched to the analytics tabs when the run finishes. All
heavy computation happens on the worker thread. Qt lives here.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from duw.config import (
    KEY_FUNDING_BPS,
    KEY_LGD,
    KEY_MC_PATHS,
    KEY_MC_SEED,
    KEY_MC_STEPS,
    KEY_THEME,
    KEY_TOOLTIPS,
    KEY_UPDATE_CHECK,
    KEY_WWR,
    AppSettings,
)
from duw.domain.counterparty import Counterparty
from duw.domain.instruments import NettingSet, Trade
from duw.domain.results import AnalysisResults
from duw.examples import Example, examples
from duw.pipeline.orchestrator import RunConfig
from duw.pipeline.worker import PipelineWorker, create_worker_thread
from duw.risk.scenarios import ScenarioSpec, apply_scenario
from duw.store.deals import Deal, DealStore, default_deal_store_path
from duw.ui.app_state import AppState
from duw.ui.dialogs import SettingsDialog, show_about, show_glossary
from duw.ui.format import short_money
from duw.ui.help import tab_help
from duw.ui.sensitivities_run import compute_async as compute_sensitivities_async
from duw.ui.tabs.collateral_tab import CollateralTab
from duw.ui.tabs.counterparty_tab import CounterpartyTab
from duw.ui.tabs.cva_tab import CvaTab
from duw.ui.tabs.exposure_tab import ExposureTab
from duw.ui.tabs.limits_tab import LimitsTab
from duw.ui.tabs.market_tab import MarketTab
from duw.ui.tabs.memo_tab import MemoTab
from duw.ui.tabs.overview_tab import OverviewTab, deal_kpis
from duw.ui.tabs.pipeline_tab import PipelineTab
from duw.ui.tabs.scenario_tab import ScenarioTab
from duw.ui.tabs.sensitivities_tab import SensitivitiesTab
from duw.ui.tabs.simulator_tab import SimulatorTab
from duw.ui.tabs.trade_tab import TradeTab
from duw.ui.theme import THEME_LABELS, THEMES, apply_theme, normalize_theme
from duw.ui.tooltips import (
    add_help_badges,
    install_tooltip_gate,
    mirror_form_label_tooltips,
    set_help_badges_visible,
)
from duw.ui.update_check import check_async
from duw.ui.widgets.app_shell import KpiStrip, NavPanel, PageHeader, TopBar, app_icon
from duw.updates import UpdateInfo

# The workflow pages, in the order a run flows through them (the Overview
# summarises the decision). Also the keys of the help registry.
TAB_NAMES: tuple[str, ...] = (
    "Overview",
    "Trade",
    "Counterparty",
    "Market",
    "Exposure",
    "Limits",
    "Collateral",
    "CVA",
    "Scenario",
    "Sensitivities",
    "Memo",
    "Pipeline",
    "Simulator",
)


# One-line page subtitles shown next to the page title.
PAGE_SUBTITLES: dict[str, str] = {
    "Overview": "Exposure, limit and credit read-out with the underwriting decision",
    "Trade": "Proposed trade and the counterparty's existing book",
    "Counterparty": "Financials, internal rating and default probability",
    "Market": "Discount curves, CDS curves and FX, as of the snapshot",
    "Exposure": "Monte Carlo EE / PFE profile of the netting set",
    "Limits": "Peak PFE against the counterparty limit",
    "Collateral": "CSA terms and their effect on exposure",
    "CVA": "CVA, DVA and FVA with per-period contributions",
    "Scenario": "Shock the market and re-run against the base",
    "Sensitivities": "DV01, CS01 and FX delta of the netting set",
    "Memo": "Credit memo preview and export (HTML / PDF / PPTX)",
    "Pipeline": "Saved deals by status",
    "Simulator": "A guided underwriting campaign with scoring",
}

# Pages that are not about the deal in the header hide the KPI strip.
_NO_KPI_PAGES = frozenset({"Pipeline", "Simulator"})


class MainWindow(QMainWindow):
    """Top-level window: deal header, grouped navigation, pages, run wiring."""

    def __init__(
        self, app_state: AppState | None = None, store: DealStore | None = None
    ) -> None:
        super().__init__()
        self.setWindowTitle("Derivatives Underwriting Workbench")
        self.setWindowIcon(app_icon())
        self.resize(1440, 900)
        self._example_name: str | None = None

        self.app_state = app_state or AppState()
        self.settings = AppSettings()
        self.store = store or DealStore(default_deal_store_path())
        self._worker: PipelineWorker | None = None
        self._thread = None
        self._run_stressed = False
        self._last_inputs: tuple | None = None
        self.results: AnalysisResults | None = None

        self.overview_tab = OverviewTab()
        self.trade_tab = TradeTab(self.app_state)
        self.counterparty_tab = CounterpartyTab(self.app_state)
        self.market_tab = MarketTab(self.app_state)
        self.exposure_tab = ExposureTab()
        self.limits_tab = LimitsTab()
        self.collateral_tab = CollateralTab()
        self.cva_tab = CvaTab()
        self.scenario_tab = ScenarioTab()
        self.scenario_tab.stressedRunRequested.connect(self._on_stressed_run)
        self.sensitivities_tab = SensitivitiesTab()
        self.sensitivities_tab.computeRequested.connect(self._on_compute_sensitivities)
        self._sens_signals = None
        self.memo_tab = MemoTab()
        self.pipeline_tab = PipelineTab(self.store)
        self.pipeline_tab.reopenRequested.connect(self._on_reopen)
        self.simulator_tab = SimulatorTab()

        self._build_tabs()
        self._build_menu_bar()
        self._build_shell()
        self._build_status_bar()

        # Global gate for the learning tooltips, toggled from the Settings menu.
        app = QApplication.instance()
        self._tooltip_gate = (
            install_tooltip_gate(app, self.settings.get_bool(KEY_TOOLTIPS))
            if app is not None
            else None
        )
        # Also show each control's tooltip when the learner hovers its form label,
        # and drop a clickable "?" help icon next to each helped field.
        mirror_form_label_tooltips(self)
        add_help_badges(self)
        set_help_badges_visible(self, self.settings.get_bool(KEY_TOOLTIPS))

        self.app_state.tradeChanged.connect(self._update_run_enabled)
        self.app_state.counterpartyChanged.connect(self._update_run_enabled)
        for signal in (
            self.app_state.tradeChanged,
            self.app_state.counterpartyChanged,
            self.app_state.bookChanged,
            self.app_state.snapshotChanged,
        ):
            signal.connect(self._update_context)
        self._update_run_enabled()
        self._update_context()
        self._on_page_changed(self.tabs.currentIndex())

        # Opt-in: check for updates on startup (off by default, offline-first).
        self._update_signals = None
        if self.settings.get_bool(KEY_UPDATE_CHECK):
            self._update_signals = check_async(self._on_update_result_startup)

    # -- construction ------------------------------------------------------ #
    def _build_tabs(self) -> None:
        self.tabs = QTabWidget()
        self.tabs.setObjectName("pageStack")
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self.overview_tab, "Overview")
        self.tabs.addTab(self.trade_tab, "Trade")
        self.tabs.addTab(self.counterparty_tab, "Counterparty")
        self.tabs.addTab(self.market_tab, "Market")
        self.tabs.addTab(self.exposure_tab, "Exposure")
        self.tabs.addTab(self.limits_tab, "Limits")
        self.tabs.addTab(self.collateral_tab, "Collateral")
        self.tabs.addTab(self.cva_tab, "CVA")
        self.tabs.addTab(self.scenario_tab, "Scenario")
        self.tabs.addTab(self.sensitivities_tab, "Sensitivities")
        self.tabs.addTab(self.memo_tab, "Memo")
        self.tabs.addTab(self.pipeline_tab, "Pipeline")
        self.tabs.addTab(self.simulator_tab, "Simulator")
        # Learning tooltip on each tab, explaining that step of the workflow.
        for i in range(self.tabs.count()):
            self.tabs.setTabToolTip(i, tab_help(self.tabs.tabText(i)))
        # The grouped navigation replaces the tab bar.
        self.tabs.tabBar().hide()

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

        # View menu — page navigation and theme selection (persisted).
        view_menu = menu_bar.addMenu("&View")
        go_menu = view_menu.addMenu("&Go to")
        for i, name in enumerate(TAB_NAMES):
            action = QAction(name, self)
            if i < 9:
                action.setShortcut(f"Ctrl+{i + 1}")
            action.triggered.connect(lambda _checked, n=name: self.show_page(n))
            go_menu.addAction(action)
        theme_menu = view_menu.addMenu("&Theme")
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        current_theme = normalize_theme(self.settings.get_str(KEY_THEME))
        for theme in THEMES:
            label = THEME_LABELS.get(theme, theme.title())
            action = QAction(label, self, checkable=True)
            action.setChecked(theme == current_theme)
            action.triggered.connect(lambda _checked, t=theme: self._set_theme(t))
            self._theme_group.addAction(action)
            theme_menu.addAction(action)

        # Settings menu — preferences and the learning-tooltips toggle.
        settings_menu = menu_bar.addMenu("&Settings")
        prefs_action = QAction("&Preferences…", self)
        prefs_action.triggered.connect(self._on_preferences)
        settings_menu.addAction(prefs_action)
        self.tooltips_action = QAction("Learning &tooltips", self, checkable=True)
        self.tooltips_action.setChecked(self.settings.get_bool(KEY_TOOLTIPS))
        self.tooltips_action.setStatusTip(
            "Show plain-English tooltips explaining each step and control."
        )
        self.tooltips_action.toggled.connect(self._set_tooltips_enabled)
        settings_menu.addAction(self.tooltips_action)

        # Help menu — examples, glossary, updates, About / disclaimer.
        help_menu = menu_bar.addMenu("&Help")
        examples_menu = help_menu.addMenu("Load &Example")
        self.examples_menu = examples_menu
        for example in examples():
            action = QAction(example.name, self)
            action.setToolTip(example.description)
            action.triggered.connect(
                lambda _checked, ex=example: self._load_example(ex)
            )
            examples_menu.addAction(action)
        examples_menu.setToolTipsVisible(True)
        glossary_action = QAction("&Glossary", self)
        glossary_action.triggered.connect(lambda: show_glossary(self))
        help_menu.addAction(glossary_action)
        help_menu.addSeparator()
        updates_action = QAction("Check for &Updates…", self)
        updates_action.triggered.connect(self._on_check_updates)
        help_menu.addAction(updates_action)
        help_menu.addSeparator()
        about_action = QAction("&About", self)
        about_action.triggered.connect(lambda: show_about(self))
        help_menu.addAction(about_action)

    def _build_shell(self) -> None:
        """Top bar (deal header) over [navigation | page title, KPIs, page]."""
        self.run_action.setToolTip(
            "Run the full underwriting analysis on the current trade and "
            "counterparty, and fill in every analytics page (Ctrl+R)."
        )
        self.top_bar = TopBar()
        self.top_bar.run_button.clicked.connect(self.run_action.trigger)
        self.top_bar.save_button.clicked.connect(self.save_deal_action.trigger)
        self.run_action.changed.connect(self._sync_action_buttons)
        self.save_deal_action.changed.connect(self._sync_action_buttons)
        examples_popup = QMenu(self.top_bar.examples_button)
        for action in self.examples_menu.actions():
            examples_popup.addAction(action)
        self.top_bar.examples_button.setMenu(examples_popup)
        self.top_bar.pageRequested.connect(self.show_page)
        self._sync_action_buttons()

        self.nav = NavPanel()
        self.nav.pageSelected.connect(self.show_page)
        self.page_header = PageHeader()
        self.kpi_strip = KpiStrip()

        content = QWidget()
        content.setObjectName("content")
        col = QVBoxLayout(content)
        col.setContentsMargins(16, 12, 16, 12)
        col.setSpacing(10)
        col.addWidget(self.page_header)
        col.addWidget(self.kpi_strip)
        col.addWidget(self.tabs, 1)
        self.tabs.currentChanged.connect(self._on_page_changed)

        body = QWidget()
        row = QHBoxLayout(body)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.nav)
        row.addWidget(content, 1)

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self.top_bar)
        outer.addWidget(body, 1)
        self.setCentralWidget(central)

    def _build_status_bar(self) -> None:
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setMaximumWidth(220)
        self.progress.setVisible(False)
        self.run_info = QLabel("")
        self.run_info.setObjectName("statusLabel")
        self.statusBar().addPermanentWidget(self.run_info)
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().showMessage("Enter a trade and counterparty to run.")

    # -- navigation and deal header ---------------------------------------- #
    def page_widget(self, name: str) -> QWidget | None:
        """The page widget for a workflow name (``"Exposure"``, ...)."""
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == name:
                return self.tabs.widget(i)
        return None

    def show_page(self, name: str) -> None:
        """Navigate to a page by its workflow name."""
        widget = self.page_widget(name)
        if widget is not None:
            self.tabs.setCurrentWidget(widget)

    def current_page(self) -> str:
        return self.tabs.tabText(self.tabs.currentIndex())

    def _on_page_changed(self, index: int) -> None:
        name = self.tabs.tabText(index)
        self.nav.select(name)
        self.page_header.set_page(self.nav.label(name), PAGE_SUBTITLES.get(name, ""))
        self.kpi_strip.setVisible(name not in _NO_KPI_PAGES)

    def _sync_action_buttons(self) -> None:
        self.top_bar.run_button.setEnabled(self.run_action.isEnabled())
        self.top_bar.save_button.setEnabled(self.save_deal_action.isEnabled())

    @staticmethod
    def _trade_summary(trade: Trade | None) -> str:
        if trade is None:
            return "No trade"
        direction = getattr(trade, "direction", None)
        side = f" {direction.name.replace('_', ' ').lower()}" if direction else ""
        return (
            f"{trade.product}{side} · {short_money(trade.notional)} {trade.currency}"
            f" · {trade.maturity_date:%b %Y}"
        )

    def _update_context(self, *_args: object) -> None:
        state = self.app_state
        cp = state.counterparty
        cp_text = "No counterparty"
        if cp is not None:
            rating = f" · {cp.internal_rating}" if cp.internal_rating else ""
            cp_text = cp.name + rating
        n = len(state.book)
        book = f"Book: {n} trade{'s' if n != 1 else ''}" if n else "Book: none"
        snap = state.snapshot
        as_of = f"Snapshot {snap.as_of:%d %b %Y}" if snap is not None else ""
        self.top_bar.set_context(cp_text, self._trade_summary(state.trade), book, as_of)

    def _set_kpis(self, results: AnalysisResults | None) -> None:
        self.kpi_strip.clear()
        for name, value, sub, tone in deal_kpis(results):
            self.kpi_strip.set_metric(name, value, sub, tone)
        cfg = results.run_config if results is not None else {}
        if cfg:
            parts = []
            if "n_paths" in cfg:
                parts.append(f"MC {int(cfg['n_paths']):,} paths")
            if "n_steps" in cfg:
                parts.append(f"{int(cfg['n_steps'])} steps")
            if "seed" in cfg:
                parts.append(f"seed {cfg['seed']}")
            lgd = cfg.get("lgd")
            if isinstance(lgd, float) and not math.isnan(lgd):
                parts.append(f"LGD {lgd:.0%}")
            self.run_info.setText(" · ".join(parts))

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
        self._start_run(
            counterparty,
            existing_set,
            trade,
            self._run_config(),
            snapshot=self.app_state.snapshot,
        )

    def _run_config(self) -> RunConfig:
        """Build a RunConfig from the persisted settings."""
        return RunConfig(
            n_paths=self.settings.get_int(KEY_MC_PATHS),
            n_steps=self.settings.get_int(KEY_MC_STEPS),
            seed=self.settings.get_int(KEY_MC_SEED),
            lgd=self.settings.get_float(KEY_LGD),
            funding_spread=self.settings.get_float(KEY_FUNDING_BPS) / 1e4,
            wwr_correlation=self.settings.get_float(KEY_WWR),
        )

    def _on_reopen(self, deal: Deal) -> None:
        """Re-run a saved deal to repopulate the analytics tabs."""
        if self._thread is not None:
            return
        counterparty, existing_set, trade, config = deal.to_run_inputs()
        self.statusBar().showMessage(f"Reopening deal: {deal.name}…")
        self._start_run(
            counterparty,
            existing_set,
            trade,
            config,
            snapshot=self.app_state.snapshot,
        )

    def _on_stressed_run(self, spec: ScenarioSpec) -> None:
        """Re-run the last base inputs against a shocked snapshot."""
        if self._last_inputs is None or self._thread is not None:
            return
        counterparty, existing_set, trade, config = self._last_inputs
        shocked = apply_scenario(self.app_state.snapshot, spec)
        self.statusBar().showMessage(f"Running stressed scenario: {spec.name}…")
        self._start_run(
            counterparty, existing_set, trade, config, snapshot=shocked, stressed=True
        )

    def _on_compute_sensitivities(self) -> None:
        """Compute DV01 / CS01 / FX delta off-thread for the last base inputs."""
        if self._last_inputs is None:
            return
        counterparty, existing_set, trade, config = self._last_inputs
        self.sensitivities_tab.set_busy(True)
        self._sens_signals = compute_sensitivities_async(
            counterparty,
            existing_set,
            trade,
            config,
            self.app_state.snapshot,
            self._on_sensitivities_result,
        )

    def _on_sensitivities_result(self, sens: object) -> None:
        self.sensitivities_tab.set_result(sens)

    def _start_run(
        self,
        counterparty: Counterparty,
        existing_set: NettingSet,
        trade: Trade,
        config: RunConfig,
        *,
        snapshot=None,
        stressed: bool = False,
    ) -> None:
        self._run_stressed = stressed
        if not stressed:
            self._last_inputs = (counterparty, existing_set, trade, config)
        self._worker = PipelineWorker(
            counterparty, existing_set, trade, config, snapshot=snapshot
        )
        self._thread = create_worker_thread(self._worker)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._thread.finished.connect(self._on_thread_finished)

        self.run_action.setEnabled(False)
        self.top_bar.set_running(True)
        self.scenario_tab.set_busy(True)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.statusBar().showMessage("Running analysis…")
        self._thread.start()

    def _on_progress(self, fraction: float, message: str) -> None:
        self.progress.setValue(int(fraction * 100))
        self.statusBar().showMessage(message)

    def _on_finished(self, results: AnalysisResults) -> None:
        if self._run_stressed:
            self.scenario_tab.set_stressed(results)
            self.statusBar().showMessage("Stressed scenario complete.")
            return
        self.results = results
        self.overview_tab.set_results(results)
        self._set_kpis(results)
        self.exposure_tab.set_results(results)
        self.limits_tab.set_results(results)
        self.collateral_tab.set_results(results)
        self.cva_tab.set_results(results)
        self.scenario_tab.set_base(results, self._last_inputs is not None)
        self.sensitivities_tab.set_ready(self._last_inputs is not None)
        self.memo_tab.set_results(results)
        self.save_deal_action.setEnabled(True)
        self.tabs.setCurrentWidget(self.overview_tab)
        self.statusBar().showMessage("Analysis complete.")

    def _on_failed(self, message: str) -> None:
        QMessageBox.critical(self, "Analysis failed", message)
        self.statusBar().showMessage("Analysis failed.")

    def _on_thread_finished(self) -> None:
        self.progress.setVisible(False)
        self.top_bar.set_running(False)
        self._thread = None
        self._worker = None
        self.scenario_tab.set_busy(False)
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

    # -- examples ---------------------------------------------------------- #
    def _load_example(self, example: Example) -> None:
        """Load a preconfigured example deal into the input tabs."""
        if not self.counterparty_tab.select_seed(example.counterparty_id):
            return
        self.app_state.clear_book()
        for trade in example.book:
            self.app_state.add_to_book(trade)
        self.trade_tab.load_trade(example.trade)
        self._example_name = example.name
        self.top_bar.set_example(example.name)
        self.tabs.setCurrentWidget(self.trade_tab)
        self.statusBar().showMessage(
            f"Loaded example: {example.name} — press Run Analysis (Ctrl+R)."
        )

    # -- updates ----------------------------------------------------------- #
    def _on_check_updates(self) -> None:
        self.statusBar().showMessage("Checking for updates…")
        self._update_signals = check_async(self._on_update_result_manual)

    def _on_update_result_manual(self, info: UpdateInfo) -> None:
        self.statusBar().showMessage(info.message)
        if info.available:
            resp = QMessageBox.information(
                self,
                "Update available",
                f"{info.message}\n\nOpen the releases page?",
                QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Close,
            )
            if resp == QMessageBox.StandardButton.Open:
                QDesktopServices.openUrl(QUrl(info.url))
        else:
            QMessageBox.information(self, "Check for updates", info.message)

    def _on_update_result_startup(self, info: UpdateInfo) -> None:
        # Non-intrusive: only surface a newer version, and only in the status bar.
        if info.available:
            self.statusBar().showMessage(info.message)

    # -- preferences and theme --------------------------------------------- #
    def _on_preferences(self) -> None:
        SettingsDialog(self.settings, self).exec()

    def _set_tooltips_enabled(self, enabled: bool) -> None:
        """Persist and apply the learning-tooltips on/off toggle."""
        self.settings.set(KEY_TOOLTIPS, enabled)
        self.settings.sync()
        if self._tooltip_gate is not None:
            self._tooltip_gate.set_enabled(enabled)
        set_help_badges_visible(self, enabled)

    def _set_theme(self, theme: str) -> None:
        self.settings.set(KEY_THEME, theme)
        self.settings.sync()
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, theme)
        self.nav.retheme()
        if self.results is not None:
            self._set_kpis(self.results)
            self.overview_tab.set_results(self.results)
        # Charts render in their own web views and do not inherit the Qt style
        # sheet, so re-skin every chart in place to match the new theme.
        from duw.ui.widgets.plotly_view import PlotlyView

        for view in self.findChildren(PlotlyView):
            view.set_theme(theme)
