"""Role-play underwriting simulator tab.

The first playable simulator screen. A student loads a scenario and plays it one
round at a time: each round an arriving deal is shown, its underwriting is run on
a background thread, and the consequences (exposure, CVA, limit use, collateral
effect) are displayed *before* the student commits. The student adjusts the CSA
and limit and watches the numbers move, then commits an approve / decline /
condition decision; the clock advances and the running book and score carry
forward. When a scripted default fires on a counterparty with open approved
trades, the flow is interrupted by a distinct default panel that ties the loss
back to the decision that took the exposure. A closing summary shows the final
score.

This tab only orchestrates and displays: it drives the pure
:class:`~duw.scenario.engine.ScenarioEngine` and :class:`~duw.scenario.scoring.Scorer`
as-is (via a background :class:`~duw.ui.simulator_run.ScenarioRunWorker`) and never
runs the engine on the UI thread or reimplements any numeric logic. Qt lives here.

Because the engine is deterministic, each round is previewed by replaying the
whole scenario with the decisions committed so far plus the candidate decision;
the current deal's outcome depends only on earlier decisions, so the replay gives
the correct preview without a stepping API on the (untouched) engine.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from duw.scenario.engine import ScenarioEngine
from duw.scenario.io import load_bundled_scenario, load_scenario
from duw.scenario.model import (
    DealArrival,
    Decision,
    DecisionAction,
    DefaultEvent,
    DefaultOutcome,
    Scenario,
    ScenarioResult,
)
from duw.scenario.scoring import Scorer, ScoreResult, score_scenario
from duw.ui.simulator_run import ScenarioRunWorker, create_scenario_thread
from duw.ui.widgets.charts import simulator_consequence_figure
from duw.ui.widgets.plotly_view import PlotlyView
from duw.ui.widgets.result_table import MetricsTable

DEFAULT_SCENARIO = "rising_rates_default"

_ACTION_LABELS: tuple[tuple[str, DecisionAction], ...] = (
    ("Approve", DecisionAction.APPROVE),
    ("Condition (collateralize)", DecisionAction.CONDITION),
    ("Decline", DecisionAction.DECLINE),
)


def _money(x: float | None) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    return f"{x:,.0f}"


@dataclass(frozen=True)
class PlayStep:
    """One step in the play sequence: a deal to decide, a default, or the end."""

    kind: str  # "decision" | "default" | "end"
    round: int
    deal: DealArrival | None = None
    default: DefaultEvent | None = None


class SimulatorTab(QWidget):
    """Load a scenario and play it round by round against the live engine."""

    #: Emitted after each background run is applied (mode: "preview"/"commit"/
    #: "failed"). Lets tests wait for the flow to settle.
    runFinished = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._scenario: Scenario | None = None
        self._steps: tuple[PlayStep, ...] = ()
        self._step_index = 0
        self._committed: dict[str, Decision] = {}
        self._last_result: ScenarioResult | None = None
        self.score_result: ScoreResult | None = None

        # Background run state.
        self._thread = None
        self._worker: ScenarioRunWorker | None = None
        self._run_mode = ""
        self._preview_pending = False

        self._build_ui()
        self._show_prompt()

    # -- construction ------------------------------------------------------ #
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        self.framing = QLabel()
        self.framing.setWordWrap(True)
        self.framing.setTextFormat(Qt.TextFormat.RichText)
        outer.addWidget(self.framing)

        splitter = QSplitter()
        self.stack = QStackedWidget()
        self._prompt_page = self._build_prompt_page()
        self._decision_page = self._build_decision_page()
        self._default_page = self._build_default_page()
        self._summary_page = self._build_summary_page()
        self.stack.addWidget(self._prompt_page)
        self.stack.addWidget(self._decision_page)
        self.stack.addWidget(self._default_page)
        self.stack.addWidget(self._summary_page)
        splitter.addWidget(self.stack)
        splitter.addWidget(self._build_scoreboard())
        splitter.setSizes([900, 320])
        outer.addWidget(splitter)

    def _build_prompt_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        intro = QLabel(
            "Play a scripted underwriting scenario round by round. Size up each "
            "deal, set collateral and limits, and live with the consequences."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.load_sample_btn = QPushButton("Load sample scenario")
        self.load_sample_btn.clicked.connect(self.load_default)
        layout.addWidget(self.load_sample_btn)
        self.load_file_btn = QPushButton("Load scenario from file…")
        self.load_file_btn.clicked.connect(self._on_load_file)
        layout.addWidget(self.load_file_btn)
        layout.addStretch(1)
        return page

    def _build_decision_page(self) -> QWidget:
        page = QSplitter()

        controls = QWidget()
        cbox = QVBoxLayout(controls)

        deal_group = QGroupBox("Deal on the table")
        deal_layout = QVBoxLayout(deal_group)
        self.deal_table = MetricsTable()
        deal_layout.addWidget(self.deal_table)
        cbox.addWidget(deal_group)

        decision_group = QGroupBox("Your decision")
        form = QFormLayout(decision_group)
        self.action_combo = QComboBox()
        for label, _action in _ACTION_LABELS:
            self.action_combo.addItem(label)
        self.action_combo.currentIndexChanged.connect(self._request_preview)
        form.addRow("Action", self.action_combo)

        self.collateral_check = QCheckBox("Require collateral (CSA)")
        self.collateral_check.toggled.connect(self._request_preview)
        form.addRow(self.collateral_check)

        self.threshold_spin = self._money_spin(0.0)
        self.mta_spin = self._money_spin(0.0)
        self.im_spin = self._money_spin(0.0)
        self.limit_spin = self._money_spin(5_000_000.0)
        form.addRow("CSA threshold", self.threshold_spin)
        form.addRow("Minimum transfer amount", self.mta_spin)
        form.addRow("Initial margin", self.im_spin)
        form.addRow("Credit limit", self.limit_spin)

        self.commit_btn = QPushButton("Commit decision → next round")
        self.commit_btn.clicked.connect(self._on_commit)
        form.addRow(self.commit_btn)

        self.decision_status = QLabel("")
        self.decision_status.setWordWrap(True)
        form.addRow(self.decision_status)
        cbox.addWidget(decision_group)
        cbox.addStretch(1)

        consequences = QWidget()
        cons_layout = QVBoxLayout(consequences)
        cons_layout.addWidget(QLabel("<b>Consequences before you commit</b>"))
        self.consequence_table = MetricsTable()
        cons_layout.addWidget(self.consequence_table)
        self.consequence_view = PlotlyView()
        cons_layout.addWidget(self.consequence_view, 1)
        self.recommendation_label = QLabel("")
        self.recommendation_label.setWordWrap(True)
        cons_layout.addWidget(self.recommendation_label)

        page.addWidget(controls)
        page.addWidget(consequences)
        page.setSizes([380, 520])
        return page

    def _build_default_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addStretch(1)
        self.default_banner = QLabel("COUNTERPARTY DEFAULT")
        self.default_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.default_banner.setStyleSheet(
            "font-size: 22px; font-weight: bold; color: #b00020; padding: 8px;"
        )
        layout.addWidget(self.default_banner)
        self.default_detail = QLabel("")
        self.default_detail.setWordWrap(True)
        self.default_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.default_detail.setStyleSheet("font-size: 14px; padding: 8px;")
        layout.addWidget(self.default_detail)
        self.default_table = MetricsTable()
        wrap = QHBoxLayout()
        wrap.addStretch(1)
        table_holder = QWidget()
        th_layout = QVBoxLayout(table_holder)
        th_layout.addWidget(self.default_table)
        table_holder.setMaximumWidth(460)
        wrap.addWidget(table_holder)
        wrap.addStretch(1)
        layout.addLayout(wrap)
        self.default_tieback = QLabel("")
        self.default_tieback.setWordWrap(True)
        self.default_tieback.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.default_tieback)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.continue_btn = QPushButton("Continue")
        self.continue_btn.clicked.connect(self._on_continue)
        btn_row.addWidget(self.continue_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)
        layout.addStretch(2)
        return page

    def _build_summary_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("<b>Scenario complete</b>"))
        layout.addWidget(QLabel("Final score breakdown:"))
        self.summary_table = MetricsTable()
        layout.addWidget(self.summary_table)
        layout.addWidget(QLabel("Round-by-round P&L:"))
        self.history_table = MetricsTable()
        self.history_table.setHorizontalHeaderLabels(["Round", "Net P&L"])
        layout.addWidget(self.history_table)
        layout.addStretch(1)
        return page

    def _build_scoreboard(self) -> QWidget:
        box = QGroupBox("Where you stand")
        layout = QVBoxLayout(box)
        self.round_label = QLabel("No scenario loaded.")
        self.round_label.setWordWrap(True)
        layout.addWidget(self.round_label)
        self.book_label = QLabel("")
        self.book_label.setWordWrap(True)
        layout.addWidget(self.book_label)
        self.score_table = MetricsTable()
        layout.addWidget(self.score_table)
        layout.addStretch(1)
        return box

    @staticmethod
    def _money_spin(default: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 1e12)
        spin.setDecimals(0)
        spin.setGroupSeparatorShown(True)
        spin.setSingleStep(100_000.0)
        spin.setValue(default)
        return spin

    # -- loading ----------------------------------------------------------- #
    def load_default(self) -> None:
        """Load the bundled sample scenario."""
        self.load_scenario_object(load_bundled_scenario(DEFAULT_SCENARIO))

    def load_from_path(self, path: str) -> None:
        """Load a scenario from a JSON file path."""
        self.load_scenario_object(load_scenario(path))

    def load_scenario_object(self, scenario: Scenario) -> None:
        """Load a :class:`Scenario` and start play at its first step."""
        self._scenario = scenario
        self._committed = {}
        self._last_result = None
        self.score_result = None
        self._steps = self._build_steps(scenario)
        self._step_index = 0
        self._render_framing()
        self._update_scoreboard()
        self._render_step()

    def _on_load_file(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        path, _filter = QFileDialog.getOpenFileName(
            self, "Load scenario", "", "Scenario JSON (*.json)"
        )
        if path:
            try:
                self.load_from_path(path)
            except Exception as exc:  # noqa: BLE001 - surface load errors gently
                self.framing.setText(f"Could not load scenario: {exc}")

    @staticmethod
    def _build_steps(scenario: Scenario) -> tuple[PlayStep, ...]:
        steps: list[PlayStep] = []
        for rnd in range(scenario.meta.n_rounds):
            for deal in scenario.deals_at(rnd):
                steps.append(PlayStep("decision", rnd, deal=deal))
            for event in scenario.defaults_at(rnd):
                steps.append(PlayStep("default", rnd, default=event))
        steps.append(PlayStep("end", max(scenario.meta.n_rounds - 1, 0)))
        return tuple(steps)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        # Auto-load the sample the first time the tab is opened, so it is
        # immediately playable without a menu action.
        super().showEvent(event)
        if self._scenario is None:
            self.load_default()

    # -- step rendering ---------------------------------------------------- #
    def _current_step(self) -> PlayStep | None:
        if 0 <= self._step_index < len(self._steps):
            return self._steps[self._step_index]
        return None

    def _render_step(self) -> None:
        step = self._current_step()
        if step is None:
            return
        self._update_scoreboard()
        if step.kind == "decision":
            self._render_decision(step)
        elif step.kind == "default":
            self._render_default(step)
        else:
            self._render_summary()

    def _render_decision(self, step: PlayStep) -> None:
        assert step.deal is not None
        self.stack.setCurrentWidget(self._decision_page)
        self.deal_table.set_metrics(self._describe_deal(step.deal))
        self.consequence_table.set_metrics([("Status", "Previewing…")])
        self.recommendation_label.setText("")
        self.decision_status.setText("")
        self._ensure_preview()
        self._update_enabled()

    def _render_default(self, step: PlayStep) -> None:
        assert step.default is not None
        outcome = self._default_outcome_for(step.default)
        # Only interrupt with the panel when there was open exposure to lose.
        if outcome is None or outcome.n_open_trades == 0:
            self._advance_step()
            return
        self.stack.setCurrentWidget(self._default_page)
        name = self._counterparty_name(step.default.counterparty_id)
        self.default_banner.setText(f"⚠  {name} HAS DEFAULTED")
        self.default_detail.setText(
            f"In round {step.default.round + 1}, {name} defaulted with "
            f"{outcome.n_open_trades} open approved trade(s) on your book."
        )
        self.default_table.set_metrics(
            [
                ("Exposure at default", _money(outcome.exposure_at_default)),
                ("Collateral held", _money(outcome.collateral_held)),
                ("Recovery rate", f"{outcome.recovery_rate:.0%}"),
                ("Realized loss", _money(outcome.realized_loss)),
            ]
        )
        self.default_tieback.setText(self._tieback_text(step.default))
        self._update_scoreboard()
        self._update_enabled()

    def _render_summary(self) -> None:
        self.stack.setCurrentWidget(self._summary_page)
        result = self._last_result or ScenarioResult()
        self.score_result = Scorer().score(result)
        b = self.score_result.breakdown
        self.summary_table.set_metrics(
            [
                ("Raw P&L", _money(self.score_result.raw_pnl)),
                ("Risk-adjusted score", _money(self.score_result.risk_adjusted_score)),
                ("Revenue", _money(b.revenue)),
                ("CVA collected", _money(b.cva_collected)),
                ("Realized losses", _money(b.realized_losses)),
                ("Exposure cost", _money(b.exposure_cost)),
                ("Breach penalty", _money(b.breach_penalty)),
                ("Risk penalty", _money(b.risk_penalty)),
            ]
        )
        history = self.score_result.by_round
        self.history_table.setRowCount(len(history))
        from PySide6.QtWidgets import QTableWidgetItem

        for r, rs in enumerate(history):
            self.history_table.setItem(r, 0, QTableWidgetItem(f"Round {rs.round + 1}"))
            self.history_table.setItem(r, 1, QTableWidgetItem(_money(rs.net)))
        self._update_scoreboard()
        self._update_enabled()

    # -- decision inputs --------------------------------------------------- #
    def _current_action(self) -> DecisionAction:
        return _ACTION_LABELS[self.action_combo.currentIndex()][1]

    def _current_candidate(self) -> Decision:
        step = self._current_step()
        trade_id = step.deal.trade_id if step and step.deal else ""
        return Decision(
            trade_id=trade_id,
            action=self._current_action(),
            require_collateral=self.collateral_check.isChecked(),
            csa_threshold=self.threshold_spin.value(),
            csa_mta=self.mta_spin.value(),
            csa_initial_margin=self.im_spin.value(),
            csa_mpor_days=10,
            limit=self.limit_spin.value(),
        )

    def set_candidate(self, decision: Decision) -> None:
        """Set the decision controls from a :class:`Decision` (used by tests)."""
        for i, (_label, action) in enumerate(_ACTION_LABELS):
            if action == decision.action:
                self.action_combo.setCurrentIndex(i)
                break
        self.collateral_check.setChecked(decision.require_collateral)
        self.threshold_spin.setValue(decision.csa_threshold)
        self.mta_spin.setValue(decision.csa_mta)
        self.im_spin.setValue(decision.csa_initial_margin)
        self.limit_spin.setValue(decision.limit)

    # -- background runs --------------------------------------------------- #
    def is_busy(self) -> bool:
        """Whether a background engine run is in flight."""
        return self._thread is not None

    def _ensure_preview(self) -> None:
        if self._thread is not None:
            self._preview_pending = True
        else:
            self._request_preview()

    def _request_preview(self, *_args: object) -> None:
        step = self._current_step()
        if self._scenario is None or step is None or step.kind != "decision":
            return
        if self._thread is not None:
            self._preview_pending = True
            return
        decisions = dict(self._committed)
        decisions[step.deal.trade_id] = self._current_candidate()
        self._start_run(decisions, "preview")

    def _on_commit(self) -> None:
        step = self._current_step()
        if self._thread is not None or step is None or step.kind != "decision":
            return
        self._committed[step.deal.trade_id] = self._current_candidate()
        self._start_run(dict(self._committed), "commit")

    def _on_continue(self) -> None:
        if self._thread is not None:
            return
        self._advance_step()

    def _advance_step(self) -> None:
        self._step_index += 1
        self._render_step()

    def _start_run(self, decisions: dict[str, Decision], mode: str) -> None:
        assert self._scenario is not None
        self._run_mode = mode
        self._worker = ScenarioRunWorker(self._scenario, decisions)
        self._thread = create_scenario_thread(self._worker)
        self._worker.finished.connect(self._on_run_finished)
        self._worker.failed.connect(self._on_run_failed)
        self._thread.finished.connect(self._on_thread_done)
        self._update_enabled()
        self._thread.start()

    def _on_run_finished(self, result: ScenarioResult) -> None:
        mode = self._run_mode
        if mode == "preview":
            self._apply_preview(result)
        else:
            self._apply_commit(result)
        self.runFinished.emit(mode)

    def _on_run_failed(self, message: str) -> None:
        self.decision_status.setText(f"Run failed: {message}")
        self.runFinished.emit("failed")

    def _on_thread_done(self) -> None:
        self._thread = None
        self._worker = None
        self._update_enabled()
        if self._preview_pending:
            self._preview_pending = False
            self._request_preview()

    def _apply_preview(self, result: ScenarioResult) -> None:
        step = self._current_step()
        if step is None or step.kind != "decision":
            return
        outcome = next(
            (o for o in result.decisions if o.trade_id == step.deal.trade_id), None
        )
        if outcome is None:
            return
        candidate = self._current_candidate()
        headroom = candidate.limit - outcome.peak_pfe
        self.consequence_table.set_metrics(
            [
                ("Peak PFE", _money(outcome.peak_pfe)),
                ("EPE", _money(outcome.epe)),
                ("Collateralized peak PFE", _money(outcome.collateralized_peak_pfe)),
                ("CVA", _money(outcome.cva)),
                ("DVA", _money(outcome.dva)),
                ("BCVA", _money(outcome.bcva)),
                ("Limit utilization", f"{outcome.limit_utilization:.0%}"),
                ("Headroom", _money(headroom)),
                ("Limit breach", "YES" if outcome.limit_breach else "no"),
            ]
        )
        self.consequence_view.set_figure(
            simulator_consequence_figure(
                outcome.peak_pfe, outcome.collateralized_peak_pfe, candidate.limit
            )
        )
        verdict = outcome.recommendation or "—"
        note = "" if outcome.accepted else " (this decision declines the deal)"
        self.recommendation_label.setText(
            f"Model recommendation: <b>{verdict}</b>{note}"
        )

    def _apply_commit(self, result: ScenarioResult) -> None:
        self._last_result = result
        self._advance_step()

    # -- scoreboard / book ------------------------------------------------- #
    def _update_scoreboard(self) -> None:
        if self._scenario is None:
            return
        step = self._current_step()
        round_no = (step.round + 1) if step else self._scenario.meta.n_rounds
        n = self._scenario.meta.n_rounds
        phase = step.kind if step else "end"
        self.round_label.setText(f"Round {min(round_no, n)} of {n} — {phase}")
        self.book_label.setText(self._book_summary())
        score = self._live_score()
        b = score.breakdown
        self.score_table.set_metrics(
            [
                ("Raw P&L", _money(score.raw_pnl)),
                ("Risk-adjusted score", _money(score.risk_adjusted_score)),
                ("Revenue", _money(b.revenue)),
                ("CVA collected", _money(b.cva_collected)),
                ("Realized losses", _money(b.realized_losses)),
                ("Exposure cost", _money(b.exposure_cost)),
                ("Breach penalty", _money(b.breach_penalty)),
            ]
        )

    def _live_score(self) -> ScoreResult:
        """Score only the events surfaced so far (committed deals + shown defaults)."""
        if self._last_result is None:
            return score_scenario(ScenarioResult())
        decided = set(self._committed)
        surfaced = {
            (s.default.round, s.default.counterparty_id)
            for s in self._steps[: self._step_index + 1]
            if s.kind == "default" and s.default is not None
        }
        decisions = tuple(
            o for o in self._last_result.decisions if o.trade_id in decided
        )
        defaults = tuple(
            d
            for d in self._last_result.defaults
            if (d.round, d.counterparty_id) in surfaced
        )
        partial = ScenarioResult(
            decisions=decisions,
            defaults=defaults,
            total_realized_loss=sum(d.realized_loss for d in defaults),
        )
        return Scorer().score(partial)

    def _book_summary(self) -> str:
        if self._scenario is None:
            return ""
        step = self._current_step()
        current_round = step.round if step else self._scenario.meta.n_rounds
        # Defaults surfaced so far close out that counterparty's book.
        defaulted = {
            s.default.counterparty_id
            for s in self._steps[: self._step_index + 1]
            if s.kind == "default" and s.default is not None
        }
        deal_cp = {d.trade_id: d.counterparty_id for d in self._scenario.deal_stream}
        open_counts: dict[str, int] = {}
        for trade_id, decision in self._committed.items():
            if not decision.accepted:
                continue
            cp = deal_cp.get(trade_id, "")
            if cp in defaulted:
                continue
            open_counts[cp] = open_counts.get(cp, 0) + 1
        if not open_counts:
            shown_round = min(current_round + 1, self._scenario.meta.n_rounds)
            return f"Open book: none (round {shown_round})"
        parts = [
            f"{self._counterparty_name(cp)}: {count}"
            for cp, count in open_counts.items()
        ]
        return "Open book — " + ", ".join(parts)

    # -- lookups / formatting ---------------------------------------------- #
    def _default_outcome_for(self, event: DefaultEvent) -> DefaultOutcome | None:
        if self._last_result is None:
            return None
        for d in self._last_result.defaults:
            if d.round == event.round and d.counterparty_id == event.counterparty_id:
                return d
        return None

    def _counterparty_name(self, counterparty_id: str) -> str:
        if self._scenario is None:
            return counterparty_id
        try:
            return self._scenario.counterparty(counterparty_id).counterparty.name
        except KeyError:
            return counterparty_id

    def _tieback_text(self, event: DefaultEvent) -> str:
        deal_cp = {d.trade_id: d for d in self._scenario.deal_stream}
        taken = []
        for trade_id, decision in self._committed.items():
            deal = deal_cp.get(trade_id)
            if (
                deal is not None
                and deal.counterparty_id == event.counterparty_id
                and decision.accepted
            ):
                how = (
                    "with collateral"
                    if decision.require_collateral
                    else "uncollateralized"
                )
                taken.append(f"{trade_id} (round {deal.round + 1}, {how})")
        if not taken:
            return "This exposure came from trades you approved earlier."
        return (
            "This is the consequence of your earlier decision to approve "
            + "; ".join(taken)
            + "."
        )

    def _describe_deal(self, deal: DealArrival) -> list[tuple[str, str]]:
        trade = deal.trade
        rows: list[tuple[str, str]] = [
            ("Counterparty", self._counterparty_name(deal.counterparty_id)),
            ("Product", trade.product),
            ("Notional", f"{trade.notional:,.0f} {trade.currency}"),
            ("Trade date", trade.trade_date.isoformat()),
            ("Maturity", trade.maturity_date.isoformat()),
            ("Tenor", f"{trade.tenor_years:.1f}y"),
        ]
        direction = getattr(trade, "direction", None)
        if direction is not None:
            rows.append(("Direction", str(direction)))
        for attr, label in (
            ("fixed_rate", "Fixed rate"),
            ("spread", "Spread"),
            ("strike", "Strike"),
            ("contract_rate", "Contract rate"),
            ("base_rate", "Base rate"),
        ):
            value = getattr(trade, attr, None)
            if value is not None:
                rows.append((label, f"{value:.4f}"))
        return rows

    # -- enable/disable ---------------------------------------------------- #
    def _update_enabled(self) -> None:
        busy = self._thread is not None
        step = self._current_step()
        is_decision = step is not None and step.kind == "decision"
        is_default = step is not None and step.kind == "default"
        for w in (
            self.action_combo,
            self.collateral_check,
            self.threshold_spin,
            self.mta_spin,
            self.im_spin,
            self.limit_spin,
            self.commit_btn,
        ):
            w.setEnabled(is_decision and not busy)
        self.continue_btn.setEnabled(is_default and not busy)

    # -- framing ----------------------------------------------------------- #
    def _render_framing(self) -> None:
        if self._scenario is None:
            return
        meta = self._scenario.meta
        objectives = "".join(f"<li>{obj}</li>" for obj in meta.learning_objectives)
        names = ", ".join(
            self._counterparty_name(cp.counterparty_id)
            for cp in self._scenario.counterparties
        )
        self.framing.setText(
            f"<h3>{meta.title}</h3>"
            f"<p>{meta.description}</p>"
            f"<p><b>{meta.n_rounds} rounds.</b> Counterparties: {names}.</p>"
            + (f"<ul>{objectives}</ul>" if objectives else "")
        )

    def _show_prompt(self) -> None:
        self.stack.setCurrentWidget(self._prompt_page)
        self.framing.setText(
            "<h3>Underwriting simulator</h3>"
            "<p>Load a scenario to begin. The bundled sample walks through rising "
            "rates and a counterparty that deteriorates and defaults.</p>"
        )


def headless_score(scenario: Scenario, decisions: dict[str, Decision]) -> ScoreResult:
    """Score a full scripted play headlessly — the reference the tab must match."""
    return Scorer().score(ScenarioEngine(scenario).run(decisions))
