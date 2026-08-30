"""Role-play underwriting simulator tab: the campaign.

The playable side of the workbench. The learner works through an ordered
campaign (:mod:`duw.scenario.campaign`) whose first stage is a guided tutorial
and whose later stages open only once the one before is cleared, so concepts
arrive in dependency order rather than in whatever order a menu happens to list.

Each stage is played round by round: a deal arrives, its underwriting runs on a
background thread, and before the analytics are revealed the learner is asked to
*predict* what they will show. Then the consequences (the counterparty's credit
dossier, the exposure profile over time, CVA, limit use, collateral effect) are
displayed and the CSA and limit can be moved with the numbers responding live,
until an approve / decline / condition decision is committed. The clock advances
and the running book and score carry forward. When a scripted default fires on a
counterparty with open approved trades, a distinct default panel ties the loss
back to the decision that took the exposure. A closing debrief scores the run
against the stage's best play, grades it skill by skill, and records the result
so the campaign progresses.

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
import random
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from duw.scenario import coaching
from duw.scenario.campaign import (
    CAMPAIGN,
    CampaignProgress,
    CampaignStage,
    StageRecord,
)
from duw.scenario.engine import ScenarioEngine
from duw.scenario.io import (
    ScenarioError,
    list_bundled_scenarios,
    list_playable_scenarios,
    load_bundled_scenario,
    load_scenario,
)
from duw.scenario.model import (
    DealArrival,
    Decision,
    DecisionAction,
    DecisionOutcome,
    DefaultEvent,
    DefaultOutcome,
    Scenario,
    ScenarioResult,
)
from duw.scenario.scoring import Scorer, ScoreResult, score_scenario
from duw.store.progress import ProgressStore
from duw.ui.help import control_help
from duw.ui.simulator_run import ScenarioRunWorker, create_scenario_thread
from duw.ui.widgets.charts import simulator_profile_figure
from duw.ui.widgets.plotly_view import PlotlyView
from duw.ui.widgets.result_table import MetricsTable

DEFAULT_SCENARIO = "rising_rates_default"
TUTORIAL_SCENARIO = "tutorial_intro"

#: Sentinel recorded in ``_predictions`` when the learner skipped the question
#: rather than answering it. Skips are not counted as wrong, only as unanswered.
PREDICTION_SKIPPED = -1

#: Default margin period of risk, in business days — the market-standard ten for
#: a daily-margined bilateral CSA, and the value a scenario inherits unless the
#: learner moves the dial.
DEFAULT_MPOR_DAYS = 10

#: Tallest the scenario framing blurb may grow before it starts scrolling. Set
#: so the deal, its controls and the consequence panel stay usable in a window
#: around a thousand pixels tall, which is the size the README screenshots use
#: and a realistic laptop.
FRAMING_MAX_HEIGHT = 210

_ACTION_LABELS: tuple[tuple[str, DecisionAction], ...] = (
    ("Approve", DecisionAction.APPROVE),
    ("Condition (collateralize)", DecisionAction.CONDITION),
    ("Decline", DecisionAction.DECLINE),
)


def _money(x: float | None) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    return f"{x:,.0f}"


def _pct(x: float | None, decimals: int = 2) -> str:
    """Format a decimal as a percentage, without collapsing tiny values to 0%.

    A Merton PD of 1e-12 is meaningfully different from a missing one, and a
    learner comparing two dossiers needs to see "<0.01%" rather than a bare
    "0.00%" that reads like a modelling failure.
    """
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    if 0.0 < x < 10.0 ** -(decimals + 2):
        return f"<{10.0 ** -(decimals + 2):.{decimals}%}"
    return f"{x:.{decimals}%}"


def _bps(x: float | None) -> str:
    """Format a decimal spread in basis points."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    return f"{x * 10_000:,.0f} bp"


def _fmt(x: float | None, decimals: int = 2) -> str:
    """Format a plain number, or an em dash when it is absent."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    return f"{x:,.{decimals}f}"


def _signed(x: float | None, decimals: int = 1) -> str:
    """Format a sensitivity, sign always shown — the direction is the lesson."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    return f"{x:+,.{decimals}f}"


def _scrolled(inner: QWidget) -> QScrollArea:
    """Wrap ``inner`` in a vertically-scrolling, frameless area.

    Keeps a column's widgets at their natural size when the window is too short
    to show them all, instead of letting the layout compress them into slivers.
    """
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    # Vertical scrolling is the point, but the horizontal bar stays available:
    # clipping content outright is worse than letting the learner reach it.
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    area.setWidget(inner)
    return area


def _collateral_rows(
    outcome: DecisionOutcome, candidate: Decision
) -> list[tuple[str, str]]:
    """Rows showing what the CSA terms bought, shown only when one is in force.

    The collateralized peak PFE alone tells the learner what they are left
    carrying but not what the agreement achieved, and it hides the fact that the
    residual is gap risk over the margin period rather than a rounding error. So
    when a CSA applies, the exposure it removed and the MPoR that leaves the rest
    uncovered are named explicitly, next to the threshold that set them.
    """
    if not candidate.require_collateral:
        return []
    gross = outcome.uncollateralized_peak_pfe
    net = outcome.collateralized_peak_pfe
    rows: list[tuple[str, str]] = []
    if not math.isnan(gross) and not math.isnan(net):
        rows.append(("Exposure removed by the CSA", _money(gross - net)))
    rows.append(("CSA threshold", _money(candidate.csa_threshold)))
    if candidate.csa_initial_margin > 0.0:
        rows.append(("Initial margin", _money(candidate.csa_initial_margin)))
    rows.append(("Margin period of risk", f"{outcome.mpor_days} business days"))
    return rows


def _sensitivity_rows(outcome: DecisionOutcome) -> list[tuple[str, str]]:
    """DV01 / CS01 / FX-delta rows, or nothing when the scenario opted out.

    Each figure is the change in the headline it names per one unit of bump: one
    basis point on rates or credit spreads, one percent on FX.
    """
    if outcome.dv01_pfe is None:
        return []
    return [
        ("DV01 of peak PFE (per 1bp rates)", _signed(outcome.dv01_pfe)),
        ("DV01 of CVA (per 1bp rates)", _signed(outcome.dv01_cva)),
        ("CS01 of CVA (per 1bp spreads)", _signed(outcome.cs01_cva)),
        ("FX delta of peak PFE (per 1% FX)", _signed(outcome.fx_delta_pfe)),
        ("FX delta of CVA (per 1% FX)", _signed(outcome.fx_delta_cva)),
    ]


@dataclass(frozen=True)
class PlayStep:
    """One step in the play sequence: a deal to decide, a default, or the end."""

    kind: str  # "decision" | "default" | "end"
    round: int
    deal: DealArrival | None = None
    default: DefaultEvent | None = None


class SimulatorTab(QWidget):
    """Play the underwriting campaign stage by stage against the live engine."""

    #: Emitted after each background run is applied (mode: "preview"/"commit"/
    #: "failed"). Lets tests wait for the flow to settle.
    runFinished = Signal(str)

    #: Emitted when the best-play benchmark run finishes.
    benchmarkReady = Signal()

    #: Emitted with the scenario name when a finished run is written into the
    #: campaign progress record.
    stageRecorded = Signal(str)

    def __init__(self, progress_store: ProgressStore | None = None) -> None:
        super().__init__()
        self._scenario: Scenario | None = None
        self._rng = random.Random()
        self._steps: tuple[PlayStep, ...] = ()
        self._step_index = 0
        self._committed: dict[str, Decision] = {}
        self._last_result: ScenarioResult | None = None
        self.score_result: ScoreResult | None = None

        # Campaign state. The store is injectable so tests can point it at a
        # temporary file instead of the learner's real progress.
        self.campaign = CAMPAIGN
        self._store = progress_store or ProgressStore()
        self._progress: CampaignProgress = self._store.load()
        #: Scenario name of the campaign stage being played, if any.
        self._stage_name: str | None = None
        #: Guards against recording the same finished run more than once (the
        #: summary can be rendered again when a late benchmark lands).
        self._recorded = False

        # Predict-then-reveal state, both keyed by trade id.
        self._predictions: dict[str, int] = {}
        self._revealed: set[str] = set()
        #: Latest preview outcome for the deal on screen, redrawn whenever the
        #: reveal state changes without needing a fresh engine run.
        self._preview_outcome: DecisionOutcome | None = None

        # Guided-mode (tutorial) state.
        self._coached = False
        self._benchmark_result: ScenarioResult | None = None
        self._benchmark_score: ScoreResult | None = None
        self._bench_thread = None
        self._bench_worker: ScenarioRunWorker | None = None
        # Bumped on each load so a stale benchmark from a prior scenario is
        # ignored when it lands.
        self._bench_gen = 0

        # Background run state.
        self._thread = None
        self._worker: ScenarioRunWorker | None = None
        self._run_mode = ""
        self._preview_pending = False
        self._commit_pending = False

        self._build_ui()
        self.show_campaign()

    # -- construction ------------------------------------------------------ #
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        # The framing blurb is long on some stages (title, description, learning
        # objectives and the guided intro). Left to size itself it takes whatever
        # height it wants and starves the decision controls below — at a 1000px
        # window the CSA dials collapsed to unreadable slivers. So it lives in a
        # scroll area capped at FRAMING_MAX_HEIGHT: short blurbs still render in
        # full, long ones scroll, and the deal below always gets its room.
        self.framing = QLabel()
        self.framing.setWordWrap(True)
        self.framing.setTextFormat(Qt.TextFormat.RichText)
        self.framing.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self._framing_scroll = QScrollArea()
        self._framing_scroll.setWidgetResizable(True)
        self._framing_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._framing_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._framing_scroll.setWidget(self.framing)
        outer.addWidget(self._framing_scroll)

        self.tutorial_check = QCheckBox(
            "Guided (tutorial) mode: explain each step and score me against best play"
        )
        self.tutorial_check.toggled.connect(self._on_tutorial_toggled)
        outer.addWidget(self.tutorial_check)

        splitter = QSplitter()
        self.stack = QStackedWidget()
        self._campaign_page = self._build_campaign_page()
        self._prompt_page = self._build_prompt_page()
        self._decision_page = self._build_decision_page()
        self._default_page = self._build_default_page()
        self._summary_page = self._build_summary_page()
        self.stack.addWidget(self._campaign_page)
        self.stack.addWidget(self._prompt_page)
        self.stack.addWidget(self._decision_page)
        self.stack.addWidget(self._default_page)
        self.stack.addWidget(self._summary_page)
        splitter.addWidget(self.stack)
        splitter.addWidget(self._build_scoreboard())
        splitter.setSizes([900, 320])
        # Stretch of 1: every pixel not needed by the framing blurb and the mode
        # checkbox goes to the deal, rather than being shared with the blurb.
        outer.addWidget(splitter, 1)

    def _set_framing(self, html: str) -> None:
        """Set the framing blurb and size its scroll area to fit, up to the cap.

        Sizing to content keeps a short blurb (the campaign page's two lines)
        from reserving the full cap's worth of blank space, while a long one
        stops at :data:`FRAMING_MAX_HEIGHT` and scrolls.
        """
        self.framing.setText(html)
        width = self._framing_scroll.viewport().width() or self.width() or 900
        needed = self.framing.heightForWidth(width)
        if needed <= 0:
            needed = self.framing.sizeHint().height()
        self._framing_scroll.setMaximumHeight(min(needed + 8, FRAMING_MAX_HEIGHT))

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        """Re-fit the framing blurb when the width changes its wrapped height."""
        super().resizeEvent(event)
        self._set_framing(self.framing.text())

    def _build_campaign_page(self) -> QWidget:
        """The stage list: what is cleared, what is open, and what comes next."""
        page = QWidget()
        layout = QVBoxLayout(page)

        self.campaign_summary = QLabel()
        self.campaign_summary.setWordWrap(True)
        self.campaign_summary.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.campaign_summary)

        body = QSplitter()
        self.stage_list = QListWidget()
        self.stage_list.currentRowChanged.connect(self._on_stage_selected)
        self.stage_list.itemDoubleClicked.connect(
            lambda _item: self.play_selected_stage()
        )
        body.addWidget(self.stage_list)

        detail_holder = QWidget()
        detail = QVBoxLayout(detail_holder)
        self.stage_detail = QLabel()
        self.stage_detail.setWordWrap(True)
        self.stage_detail.setTextFormat(Qt.TextFormat.RichText)
        self.stage_detail.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.stage_detail)
        detail.addWidget(scroll, 1)
        self.play_stage_btn = QPushButton("Play this stage")
        self.play_stage_btn.clicked.connect(self.play_selected_stage)
        detail.addWidget(self.play_stage_btn)
        body.addWidget(detail_holder)
        # Wide enough for the longest stage title plus its medal annotation
        # ("17. Capstone: the crunch — Gold, 100% of best play"); at 340 the
        # annotation was clipped and the list grew a horizontal scrollbar.
        body.setSizes([430, 430])
        layout.addWidget(body, 1)

        controls = QHBoxLayout()
        self.continue_campaign_btn = QPushButton("Continue campaign")
        self.continue_campaign_btn.clicked.connect(self.continue_campaign)
        controls.addWidget(self.continue_campaign_btn)
        self.free_play_btn = QPushButton("Free play…")
        self.free_play_btn.setToolTip(
            "Load any bundled scenario, a random one, or a scenario file, "
            "outside the campaign."
        )
        self.free_play_btn.clicked.connect(self._show_prompt)
        controls.addWidget(self.free_play_btn)
        controls.addStretch(1)
        self.practice_check = QCheckBox("Practice mode (unlock every stage)")
        self.practice_check.setToolTip(
            "Open every stage without clearing it, to revisit a topic or "
            "demonstrate one. Your cleared stages and medals are unaffected."
        )
        self.practice_check.toggled.connect(self._on_practice_toggled)
        controls.addWidget(self.practice_check)
        self.reset_progress_btn = QPushButton("Reset progress")
        self.reset_progress_btn.clicked.connect(self._on_reset_progress)
        controls.addWidget(self.reset_progress_btn)
        layout.addLayout(controls)
        return page

    def _build_prompt_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        intro = QLabel(
            "Play a scripted underwriting scenario round by round. Size up each "
            "deal, set collateral and limits, and live with the consequences."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.load_tutorial_btn = QPushButton(
            "Start guided tutorial (new to this? start here)"
        )
        self.load_tutorial_btn.clicked.connect(self.load_tutorial)
        layout.addWidget(self.load_tutorial_btn)

        # Picker over the bundled scenarios (the defaulting sample, the no-default
        # steady book, and the tutorial), so more than one is reachable.
        picker_row = QHBoxLayout()
        self.scenario_combo = QComboBox()
        for name, title in list_bundled_scenarios():
            self.scenario_combo.addItem(title, name)
        default_idx = self.scenario_combo.findData(DEFAULT_SCENARIO)
        if default_idx >= 0:
            self.scenario_combo.setCurrentIndex(default_idx)
        picker_row.addWidget(self.scenario_combo, 1)
        self.load_selected_btn = QPushButton("Load selected scenario")
        self.load_selected_btn.clicked.connect(self._on_load_selected)
        picker_row.addWidget(self.load_selected_btn)
        layout.addLayout(picker_row)

        self.load_random_btn = QPushButton("Play a random scenario (surprise me)")
        self.load_random_btn.clicked.connect(self.load_random)
        layout.addWidget(self.load_random_btn)

        self.load_file_btn = QPushButton("Load scenario from file…")
        self.load_file_btn.clicked.connect(self._on_load_file)
        layout.addWidget(self.load_file_btn)
        self.to_campaign_btn = QPushButton("← Back to the campaign")
        self.to_campaign_btn.clicked.connect(self.show_campaign)
        layout.addWidget(self.to_campaign_btn)
        layout.addStretch(1)
        return page

    def _build_decision_page(self) -> QWidget:
        page = QSplitter()

        controls = QWidget()
        cbox = QVBoxLayout(controls)

        # Coach panel — only shown in guided (tutorial) mode.
        self.coach_group = QGroupBox("Coach")
        coach_layout = QVBoxLayout(self.coach_group)
        self.coach_text = QLabel("")
        self.coach_text.setWordWrap(True)
        coach_layout.addWidget(self.coach_text)
        self.coach_reco = QLabel("")
        self.coach_reco.setWordWrap(True)
        self.coach_reco.setTextFormat(Qt.TextFormat.RichText)
        coach_layout.addWidget(self.coach_reco)
        self.apply_reco_btn = QPushButton("Apply recommended")
        self.apply_reco_btn.clicked.connect(self._apply_recommended)
        coach_layout.addWidget(self.apply_reco_btn)
        self.on_track_label = QLabel("")
        self.on_track_label.setWordWrap(True)
        coach_layout.addWidget(self.on_track_label)
        self.coach_group.setVisible(False)
        cbox.addWidget(self.coach_group)

        deal_group = QGroupBox("Deal on the table")
        deal_layout = QVBoxLayout(deal_group)
        self.deal_table = MetricsTable()
        deal_layout.addWidget(self.deal_table)
        cbox.addWidget(deal_group)

        # The credit evidence. Without this the learner can only be *told* who
        # is risky; with it they can work it out, which is the actual skill.
        dossier_group = QGroupBox("Counterparty")
        dossier_layout = QVBoxLayout(dossier_group)
        self.dossier_table = MetricsTable()
        self.dossier_table.setToolTip(
            "What the credit models make of this counterparty. Distance-to-"
            "default counts standard deviations of asset value between the firm "
            "and its debt; the Merton PD turns that into a one-year default "
            "probability; the Altman zone scores the balance sheet; the CDS "
            "spread is what the market charges today to insure the name."
        )
        dossier_layout.addWidget(self.dossier_table)
        cbox.addWidget(dossier_group)

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
        self.mpor_spin = self._mpor_spin(DEFAULT_MPOR_DAYS)
        self.limit_spin = self._money_spin(5_000_000.0)
        self.action_combo.setToolTip(control_help("sim_action"))
        self.collateral_check.setToolTip(control_help("sim_collateral"))
        self.threshold_spin.setToolTip(control_help("csa_threshold"))
        self.mta_spin.setToolTip(control_help("csa_mta"))
        self.im_spin.setToolTip(control_help("csa_im"))
        self.mpor_spin.setToolTip(control_help("csa_mpor"))
        self.limit_spin.setToolTip(control_help("sim_limit"))
        form.addRow("CSA threshold", self.threshold_spin)
        form.addRow("Minimum transfer amount", self.mta_spin)
        form.addRow("Initial margin", self.im_spin)
        form.addRow("Margin period of risk (days)", self.mpor_spin)
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

        # Predict-then-reveal. The analytics are withheld until the learner
        # commits to an expectation, so they discover what they actually believe
        # instead of nodding along to a number that is already on screen.
        self.prediction_group = QGroupBox("Before you look: what do you expect?")
        pred_layout = QVBoxLayout(self.prediction_group)
        self.prediction_prompt = QLabel("")
        self.prediction_prompt.setWordWrap(True)
        pred_layout.addWidget(self.prediction_prompt)
        self.prediction_buttons = QButtonGroup(self)
        self.prediction_buttons.setExclusive(True)
        self._prediction_options: list[QRadioButton] = []
        #: Row widgets holding each radio button and its wrapping label.
        self._prediction_rows: list[QWidget] = []
        self._prediction_holder = QWidget()
        self._prediction_holder_layout = QVBoxLayout(self._prediction_holder)
        self._prediction_holder_layout.setContentsMargins(0, 0, 0, 0)
        pred_layout.addWidget(self._prediction_holder)
        pred_buttons = QHBoxLayout()
        self.answer_btn = QPushButton("Lock in my answer")
        self.answer_btn.clicked.connect(self._on_answer_prediction)
        pred_buttons.addWidget(self.answer_btn)
        self.skip_prediction_btn = QPushButton("Skip, just show the numbers")
        self.skip_prediction_btn.clicked.connect(self._on_skip_prediction)
        pred_buttons.addWidget(self.skip_prediction_btn)
        pred_buttons.addStretch(1)
        pred_layout.addLayout(pred_buttons)
        self.prediction_feedback = QLabel("")
        self.prediction_feedback.setWordWrap(True)
        self.prediction_feedback.setTextFormat(Qt.TextFormat.RichText)
        self.prediction_feedback.setVisible(False)
        pred_layout.addWidget(self.prediction_feedback)
        self.prediction_group.setVisible(False)
        cons_layout.addWidget(self.prediction_group)

        self.consequence_header = QLabel("<b>Consequences before you commit</b>")
        cons_layout.addWidget(self.consequence_header)
        self.consequence_table = MetricsTable()
        cons_layout.addWidget(self.consequence_table)
        self.consequence_view = PlotlyView()
        # The profile is the point of the panel — how the exposure is shaped
        # over time, not just how big it peaks — so it keeps a legible height
        # and the column scrolls rather than flattening it to a strip.
        self.consequence_view.setMinimumHeight(260)
        cons_layout.addWidget(self.consequence_view, 1)
        self.recommendation_label = QLabel("")
        self.recommendation_label.setWordWrap(True)
        cons_layout.addWidget(self.recommendation_label)

        # Both columns scroll, as the prompt and summary pages already do. The
        # decision page carries the most content of any page — coach, deal,
        # credit dossier and five decision controls on the left; prediction,
        # a dozen consequence rows and the exposure profile on the right — and
        # without scrolling a window around a thousand pixels tall squeezed the
        # CSA dials down to unreadable slivers and flattened the chart.
        page.addWidget(_scrolled(controls))
        page.addWidget(_scrolled(consequences))
        page.setSizes([400, 560])
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
        # Always-visible reframing: the default is scripted, so success is about
        # protection, not prevention. Shown in every mode.
        self.default_framing = QLabel("")
        self.default_framing.setWordWrap(True)
        self.default_framing.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.default_framing.setStyleSheet("font-size: 13px; padding: 6px;")
        layout.addWidget(self.default_framing)
        self.default_coach = QLabel("")
        self.default_coach.setWordWrap(True)
        self.default_coach.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.default_coach.setStyleSheet("padding: 8px;")
        self.default_coach.setVisible(False)
        layout.addWidget(self.default_coach)
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
        outer = QVBoxLayout(page)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        layout.addWidget(QLabel("<b>Scenario complete</b>"))

        # Campaign banner: cleared or not, and what that opened.
        self.stage_outcome = QLabel("")
        self.stage_outcome.setWordWrap(True)
        self.stage_outcome.setTextFormat(Qt.TextFormat.RichText)
        self.stage_outcome.setVisible(False)
        layout.addWidget(self.stage_outcome)

        # Skills debrief: which parts of the job went well, versus best play.
        self.skills_group = QGroupBox("Your underwriting, skill by skill")
        skills_layout = QVBoxLayout(self.skills_group)
        self.skills_table = MetricsTable()
        self.skills_table.setHorizontalHeaderLabels(["Skill", "How it went"])
        skills_layout.addWidget(self.skills_table)
        self.prediction_score = QLabel("")
        self.prediction_score.setWordWrap(True)
        skills_layout.addWidget(self.prediction_score)
        self.skills_group.setVisible(False)
        layout.addWidget(self.skills_group)

        # Verdict box — only populated in guided mode, once the benchmark lands.
        self.verdict_group = QGroupBox("How you did")
        verdict_layout = QVBoxLayout(self.verdict_group)
        self.verdict_headline = QLabel("")
        self.verdict_headline.setWordWrap(True)
        self.verdict_headline.setTextFormat(Qt.TextFormat.RichText)
        verdict_layout.addWidget(self.verdict_headline)
        success_meaning = QLabel(
            "A successful underwrite is measured by your realized loss and "
            "risk-adjusted return, not by whether a counterparty defaulted. "
            "Defaults here are scripted and will happen; the job is to be "
            "protected and still get paid."
        )
        success_meaning.setWordWrap(True)
        success_meaning.setStyleSheet("font-size: 12px;")
        verdict_layout.addWidget(success_meaning)
        self.verdict_notes = QLabel("")
        self.verdict_notes.setWordWrap(True)
        self.verdict_notes.setTextFormat(Qt.TextFormat.RichText)
        verdict_layout.addWidget(self.verdict_notes)
        self.outro_label = QLabel("")
        self.outro_label.setWordWrap(True)
        verdict_layout.addWidget(self.outro_label)
        self.verdict_group.setVisible(False)
        layout.addWidget(self.verdict_group)

        layout.addWidget(QLabel("Final score breakdown:"))
        self.summary_table = MetricsTable()
        layout.addWidget(self.summary_table)
        layout.addWidget(QLabel("Round-by-round P&L:"))
        self.history_table = MetricsTable()
        self.history_table.setHorizontalHeaderLabels(["Round", "Net P&L"])
        layout.addWidget(self.history_table)

        # Replay controls, so a finished run can be reset and played again.
        replay_row = QHBoxLayout()
        self.replay_btn = QPushButton("Play this scenario again")
        self.replay_btn.clicked.connect(self.restart_scenario)
        replay_row.addWidget(self.replay_btn)
        self.random_again_btn = QPushButton("Play a random scenario")
        self.random_again_btn.clicked.connect(self.load_random)
        replay_row.addWidget(self.random_again_btn)
        self.back_to_campaign_btn = QPushButton("Back to the campaign")
        self.back_to_campaign_btn.clicked.connect(self.show_campaign)
        replay_row.addWidget(self.back_to_campaign_btn)
        self.choose_btn = QPushButton("Choose another scenario")
        self.choose_btn.clicked.connect(self._show_prompt)
        replay_row.addWidget(self.choose_btn)
        layout.addLayout(replay_row)

        layout.addStretch(1)
        return page

    def _build_scoreboard(self) -> QWidget:
        box = QGroupBox("Where you stand")
        # Without a floor the splitter squeezed this column until "Risk-adjusted
        # score" and "CVA collected" wrapped into ellipses, which is the one
        # place the learner reads how they are doing.
        box.setMinimumWidth(260)
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

    def _money_spin(self, default: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 1e12)
        spin.setDecimals(0)
        spin.setGroupSeparatorShown(True)
        spin.setSingleStep(100_000.0)
        spin.setValue(default)
        # The CSA terms and the limit are meant to be moved with the consequence
        # panel responding, so every one of them re-previews. Bursts from a drag
        # are absorbed by the single-slot coalescing in _ensure_preview.
        spin.valueChanged.connect(self._request_preview)
        return spin

    def _mpor_spin(self, default: int) -> QSpinBox:
        """The margin period of risk dial, in business days.

        Ranged from one day (cleared-style daily margining) to sixty (a stale,
        heavily disputed agreement) so the learner can see the residual exposure
        a zero-threshold CSA still leaves when collateral cannot be called
        quickly — the gap risk the threshold alone never shows.
        """
        spin = QSpinBox()
        spin.setRange(1, 60)
        spin.setSingleStep(1)
        spin.setValue(default)
        spin.valueChanged.connect(self._request_preview)
        return spin

    # -- campaign ---------------------------------------------------------- #
    def show_campaign(self) -> None:
        """Show the stage list, refreshed from the current progress."""
        self._render_campaign()
        self.stack.setCurrentWidget(self._campaign_page)
        # The count comes from the campaign itself: spelling it out in the copy
        # silently goes stale the moment a stage is added.
        self._set_framing(
            "<h3>Underwriting campaign</h3>"
            f"<p>{len(self.campaign)} stages, in teaching order. Each one is a "
            "scripted book you underwrite deal by deal, and each opens once you "
            "have cleared the one before it. Start at the top: the first stage "
            "is a guided tutorial.</p>"
        )

    def _render_campaign(self) -> None:
        """Repaint the stage list and the header from ``self._progress``."""
        cleared = self._progress.cleared_count(self.campaign)
        medals = self._progress.medal_counts(self.campaign)
        medal_txt = ", ".join(f"{n} {name.lower()}" for name, n in medals.items() if n)
        next_stage = self._progress.next_stage(self.campaign)
        if next_stage is None:
            tail = "<b>Campaign complete.</b> Replay any stage to raise its medal."
        else:
            tail = f"Up next: <b>{next_stage.title}</b>."
        self.campaign_summary.setText(
            f"<p><b>{cleared} of {len(self.campaign)} stages cleared.</b>"
            + (f" Medals: {medal_txt}." if medal_txt else "")
            + f" {tail}</p>"
        )

        row = max(self.stage_list.currentRow(), 0)
        self.stage_list.blockSignals(True)
        self.stage_list.clear()
        for stage in self.campaign:
            unlocked = self._progress.is_unlocked(self.campaign, stage.scenario_name)
            record = self._progress.record(stage.scenario_name)
            item = QListWidgetItem(self._stage_label(stage, unlocked, record))
            if not unlocked:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.stage_list.addItem(item)
        self.stage_list.blockSignals(False)
        self.stage_list.setCurrentRow(min(row, self.stage_list.count() - 1))
        self.practice_check.blockSignals(True)
        self.practice_check.setChecked(self._progress.practice_mode)
        self.practice_check.blockSignals(False)
        self._on_stage_selected(self.stage_list.currentRow())

    @staticmethod
    def _stage_label(
        stage: CampaignStage, unlocked: bool, record: StageRecord | None
    ) -> str:
        if not unlocked:
            return f"🔒  {stage.title}"
        if record is None or not record.plays:
            return f"▸  {stage.title}"
        mark = "✓" if record.cleared else "•"
        bits = [f"{record.best_ratio:.0%} of best play"]
        if record.medal:
            bits.insert(0, record.medal)
        return f"{mark}  {stage.title}  —  {', '.join(bits)}"

    def _selected_stage(self) -> CampaignStage | None:
        row = self.stage_list.currentRow()
        if 0 <= row < len(self.campaign):
            return self.campaign.stages[row]
        return None

    def _on_stage_selected(self, _row: int) -> None:
        stage = self._selected_stage()
        if stage is None:
            self.stage_detail.setText("")
            self.play_stage_btn.setEnabled(False)
            return
        unlocked = self._progress.is_unlocked(self.campaign, stage.scenario_name)
        self.play_stage_btn.setEnabled(unlocked)
        record = self._progress.record(stage.scenario_name)

        try:
            meta = load_bundled_scenario(stage.scenario_name).meta
        except ScenarioError:  # pragma: no cover - defensive against a bad bundle
            self.stage_detail.setText(
                f"<h3>{stage.title}</h3><p>This stage's scenario file could not "
                "be loaded.</p>"
            )
            return

        objectives = "".join(f"<li>{o}</li>" for o in meta.learning_objectives)
        if not unlocked:
            idx = self.campaign.index_of(stage.scenario_name)
            previous = self.campaign.stages[idx - 1].title
            status = (
                f"<p><i>Locked. Clear <b>{previous}</b> to open it, or turn on "
                "practice mode.</i></p>"
            )
        elif record is None or not record.plays:
            status = (
                f"<p><i>Not yet played. Clears at {stage.pass_ratio:.0%} of the "
                "best play.</i></p>"
            )
        else:
            verb = "Cleared" if record.cleared else "Attempted"
            status = (
                f"<p><i>{verb} — best {record.best_ratio:.0%} of best play over "
                f"{record.plays} attempt(s)"
                + (f", {record.medal.lower()} medal" if record.medal else "")
                + f". Clears at {stage.pass_ratio:.0%}.</i></p>"
            )
        self.stage_detail.setText(
            f"<h3>{stage.title}</h3>"
            f"<p><b>What this stage teaches:</b> {stage.concept}</p>"
            f"{status}"
            f"<p><b>{meta.title}</b> — {meta.description}</p>"
            f"<p>{meta.n_rounds} rounds.</p>"
            + (f"<p><b>You should come away able to:</b></p><ul>{objectives}</ul>")
        )

    def play_selected_stage(self) -> None:
        """Load and start the stage currently selected in the list."""
        stage = self._selected_stage()
        if stage is None:
            return
        if not self._progress.is_unlocked(self.campaign, stage.scenario_name):
            return
        self.play_stage(stage)

    def play_stage(self, stage: CampaignStage) -> None:
        """Load ``stage``'s scenario and begin playing it as a campaign stage."""
        self._stage_name = stage.scenario_name
        self.load_scenario_object(load_bundled_scenario(stage.scenario_name))

    def continue_campaign(self) -> None:
        """Jump straight into the first stage that has not been cleared."""
        stage = self._progress.next_stage(self.campaign) or self.campaign.stages[0]
        idx = self.campaign.index_of(stage.scenario_name)
        if idx >= 0:
            self.stage_list.setCurrentRow(idx)
        self.play_stage(stage)

    def _on_practice_toggled(self, checked: bool) -> None:
        self._progress = self._progress.with_practice_mode(checked)
        self._save_progress()
        self._render_campaign()

    def _on_reset_progress(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        confirm = QMessageBox.question(
            self,
            "Reset campaign progress",
            "Clear every cleared stage, medal, and best score? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.reset_progress()

    def reset_progress(self) -> None:
        """Clear all campaign progress (keeping the practice-mode preference)."""
        self._progress = self._progress.reset()
        self._save_progress()
        self._render_campaign()

    def _save_progress(self) -> None:
        """Persist progress, tolerating an unwritable store rather than failing.

        Losing a saved place is a nuisance; a crash mid-game because the home
        directory is read-only would be worse, so a failed write is swallowed.
        """
        try:
            self._store.save(self._progress)
        except OSError:  # pragma: no cover - depends on the filesystem
            pass

    def _record_stage_result(self) -> None:
        """Write the finished run into the campaign record, once.

        Needs the best-play benchmark to know the ratio, so it is called both
        when the summary renders and when a late benchmark lands; the
        ``_recorded`` latch makes the second call a no-op.
        """
        if self._recorded or self._stage_name is None:
            return
        stage = self.campaign.stage(self._stage_name)
        if stage is None or self._benchmark_score is None or self.score_result is None:
            return
        target = self._benchmark_score.risk_adjusted_score
        student = self.score_result.risk_adjusted_score
        ratio = student / target if target > 0 else (1.0 if student >= target else 0.0)
        self._progress = self._progress.with_result(stage, ratio, student)
        self._save_progress()
        self._recorded = True
        self._render_campaign()
        self._render_stage_outcome(stage, ratio)
        self.stageRecorded.emit(stage.scenario_name)

    def _render_stage_outcome(self, stage: CampaignStage, ratio: float) -> None:
        """The "stage cleared / not yet" banner on the summary page."""
        from duw.scenario.campaign import medal as medal_for

        earned = medal_for(ratio)
        if ratio >= stage.pass_ratio:
            nxt = self._progress.next_stage(self.campaign)
            unlocked = (
                f" <b>{nxt.title}</b> is now open."
                if nxt is not None and nxt.scenario_name != stage.scenario_name
                else " That was the last stage — the campaign is complete."
            )
            self.stage_outcome.setText(
                f"<b>Stage cleared</b> at {ratio:.0%} of the best play"
                + (f", {earned.lower()} medal." if earned else ".")
                + unlocked
            )
        else:
            self.stage_outcome.setText(
                f"<b>Stage not cleared.</b> You scored {ratio:.0%} of the best "
                f"play and this stage needs {stage.pass_ratio:.0%}. Read the "
                "skills breakdown below, then play it again."
            )
        self.stage_outcome.setVisible(True)

    # -- loading ----------------------------------------------------------- #
    def load_bundled(self, name: str) -> None:
        """Load a bundled scenario by file stem, as its campaign stage if it is one.

        Playing a stage's scenario from the free-play picker is the same act as
        playing it from the stage list, so it counts towards the campaign either
        way; only a scenario from outside the bundle records nothing.
        """
        self._stage_name = name if self.campaign.index_of(name) >= 0 else None
        self.load_scenario_object(load_bundled_scenario(name))

    def load_default(self) -> None:
        """Load the bundled sample scenario."""
        self.load_bundled(DEFAULT_SCENARIO)

    def load_tutorial(self) -> None:
        """Load the bundled guided tutorial scenario in coached mode."""
        self._set_coached(True)
        self.load_bundled(TUTORIAL_SCENARIO)

    def load_from_path(self, path: str) -> None:
        """Load a scenario from a JSON file path (outside the campaign)."""
        self._stage_name = None
        self.load_scenario_object(load_scenario(path))

    def _on_load_selected(self) -> None:
        name = self.scenario_combo.currentData()
        if name:
            self.load_bundled(name)

    def load_random(self) -> None:
        """Load a randomly chosen playable (non-tutorial) scenario."""
        names = [name for name, _title in list_playable_scenarios()]
        if not names:
            return
        self.load_bundled(self._rng.choice(names))

    def restart_scenario(self) -> None:
        """Reset the current scenario to round one so it can be replayed."""
        if self._scenario is not None:
            self.load_scenario_object(self._scenario)

    def load_scenario_object(self, scenario: Scenario) -> None:
        """Load a :class:`Scenario` and start play at its first step."""
        self._scenario = scenario
        self._committed = {}
        self._last_result = None
        self.score_result = None
        self._predictions = {}
        self._revealed = set()
        self._recorded = False
        self.stage_outcome.setVisible(False)
        self.skills_group.setVisible(False)
        # A scenario flagged as a tutorial turns guided mode on automatically.
        if scenario.meta.tutorial:
            self._set_coached(True)
        # Reset any benchmark from a prior scenario; a stale in-flight run is
        # discarded by the generation token when it lands.
        self._bench_gen += 1
        self._benchmark_result = None
        self._benchmark_score = None
        self._steps = self._build_steps(scenario)
        self._step_index = 0
        self._update_coach_visibility()
        # The benchmark runs for every scenario, not only coached ones: the
        # campaign grades a stage as a fraction of the best play, so the
        # reference run is needed whether or not the coach panel is showing.
        if coaching.has_benchmark(scenario):
            self._start_benchmark()
        self._render_framing()
        self._update_scoreboard()
        self._render_step()

    def _set_coached(self, enabled: bool) -> None:
        """Set guided mode and sync the checkbox without re-triggering it."""
        self._coached = enabled
        self.tutorial_check.blockSignals(True)
        self.tutorial_check.setChecked(enabled)
        self.tutorial_check.blockSignals(False)
        self._update_coach_visibility()

    def _on_tutorial_toggled(self, checked: bool) -> None:
        self._coached = checked
        self._update_coach_visibility()
        if (
            checked
            and self._scenario is not None
            and self._benchmark_result is None
            and coaching.has_benchmark(self._scenario)
        ):
            self._start_benchmark()
        self._render_framing()
        # Refresh only the coach content in place — a full re-render would restart
        # the preview run, so toggling never spawns background work here.
        step = self._current_step()
        if step is not None and step.kind == "decision" and checked:
            self._update_coach_panel(step)
        elif step is not None and step.kind == "end":
            self._render_summary_verdict()
        self._update_enabled()

    def _update_coach_visibility(self) -> None:
        self.coach_group.setVisible(self._coached)
        self.default_coach.setVisible(self._coached)
        self.verdict_group.setVisible(self._coached)

    def _on_load_file(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        path, _filter = QFileDialog.getOpenFileName(
            self, "Load scenario", "", "Scenario JSON (*.json)"
        )
        if path:
            try:
                self.load_from_path(path)
            except Exception as exc:  # noqa: BLE001 - surface load errors gently
                self._set_framing(f"Could not load scenario: {exc}")

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
        # Open on the stage list rather than dropping the learner into an
        # arbitrary scenario: the campaign is the intended way in, and its first
        # stage is the tutorial.
        super().showEvent(event)
        if self._scenario is None:
            self.show_campaign()

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
        self._preview_outcome = None
        self.deal_table.set_metrics(self._describe_deal(step.deal))
        self.dossier_table.set_metrics([("Assessing credit", "…")])
        self.consequence_table.set_metrics([("Status", "Previewing…")])
        self.recommendation_label.setText("")
        self.decision_status.setText("")
        self._apply_committee_limit(step.deal)
        self._render_prediction(step.deal)
        if self._coached:
            self._update_coach_panel(step)
        self._ensure_preview()
        self._update_enabled()

    def _apply_committee_limit(self, deal: DealArrival) -> None:
        """Pin and lock the limit box when the scenario's committee set one.

        A limit the learner can raise at will teaches nothing, so a scenario
        counterparty carrying a ``credit_limit`` shows it as fixed and read-only.
        """
        limit = self._committee_limit(deal.counterparty_id)
        if limit is None:
            self.limit_spin.setReadOnly(False)
            self.limit_spin.setToolTip(control_help("sim_limit"))
            return
        self.limit_spin.blockSignals(True)
        self.limit_spin.setValue(limit)
        self.limit_spin.blockSignals(False)
        self.limit_spin.setReadOnly(True)
        self.limit_spin.setToolTip(
            "Set by the credit committee for this counterparty and fixed for "
            "the scenario. Your job is to underwrite inside it, not to move it."
        )

    def _committee_limit(self, counterparty_id: str) -> float | None:
        """The scenario-imposed limit for a counterparty, if it has one."""
        if self._scenario is None:
            return None
        try:
            return self._scenario.counterparty(counterparty_id).credit_limit
        except KeyError:
            return None

    # -- predict-then-reveal ------------------------------------------------ #
    def _render_prediction(self, deal: DealArrival) -> None:
        """Show the deal's prediction question, or nothing if it has none."""
        for button in self._prediction_options:
            self.prediction_buttons.removeButton(button)
        for row in self._prediction_rows:
            row.setParent(None)
        self._prediction_options = []
        self._prediction_rows = []
        self.prediction_feedback.setVisible(False)
        self.prediction_feedback.setText("")

        prediction = deal.prediction
        if prediction is None:
            self.prediction_group.setVisible(False)
            return
        self.prediction_group.setVisible(True)
        self.prediction_prompt.setText(prediction.prompt)
        for i, option in enumerate(prediction.options):
            # A QRadioButton will not wrap its own label, and these options run
            # to a full sentence: left on the button the text set a minimum
            # width that dragged the whole consequence column wider than the
            # window and pushed the table's VALUE column out of sight. So the
            # button carries no text and a wrapping label sits beside it.
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            button = QRadioButton()
            button.setEnabled(True)
            row_layout.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
            label = QLabel(option)
            label.setWordWrap(True)
            # Clicking the text should select the option, as it would on a
            # normal radio button.
            label.mousePressEvent = lambda _e, b=button: b.setChecked(True)
            row_layout.addWidget(label, 1)
            self.prediction_buttons.addButton(button, i)
            self._prediction_holder_layout.addWidget(row)
            self._prediction_options.append(button)
            self._prediction_rows.append(row)
        answered = deal.trade_id in self._predictions
        self.answer_btn.setEnabled(not answered)
        self.skip_prediction_btn.setEnabled(not answered)
        if answered:
            self._show_prediction_feedback(deal, self._predictions[deal.trade_id])

    def _on_answer_prediction(self) -> None:
        step = self._current_step()
        if step is None or step.deal is None or step.deal.prediction is None:
            return
        chosen = self.prediction_buttons.checkedId()
        if chosen < 0:
            self.prediction_feedback.setText("Pick an option first.")
            self.prediction_feedback.setVisible(True)
            return
        self._predictions[step.deal.trade_id] = chosen
        self._show_prediction_feedback(step.deal, chosen)
        self._reveal(step.deal.trade_id)

    def _on_skip_prediction(self) -> None:
        step = self._current_step()
        if step is None or step.deal is None:
            return
        self._predictions[step.deal.trade_id] = PREDICTION_SKIPPED
        self.answer_btn.setEnabled(False)
        self.skip_prediction_btn.setEnabled(False)
        self._reveal(step.deal.trade_id)

    def _show_prediction_feedback(self, deal: DealArrival, chosen: int) -> None:
        prediction = deal.prediction
        if prediction is None:
            return
        for i, button in enumerate(self._prediction_options):
            button.setEnabled(False)
            if i == chosen:
                button.setChecked(True)
        self.answer_btn.setEnabled(False)
        self.skip_prediction_btn.setEnabled(False)
        if chosen == PREDICTION_SKIPPED:
            verdict = "<b>Skipped.</b>"
        elif prediction.is_correct(chosen):
            verdict = "<b>Correct.</b>"
        else:
            answer = prediction.options[prediction.correct_index]
            verdict = f"<b>Not quite.</b> The answer was: <i>{answer}</i>"
        self.prediction_feedback.setText(f"{verdict} {prediction.explanation}")
        self.prediction_feedback.setVisible(True)

    def _reveal(self, trade_id: str) -> None:
        """Unhide the analytics for a deal once its question is dealt with."""
        self._revealed.add(trade_id)
        self._render_consequences()

    def _is_revealed(self, deal: DealArrival | None) -> bool:
        """Whether this deal's analytics should be on screen yet."""
        if deal is None:
            return True
        if deal.prediction is None:
            return True
        return deal.trade_id in self._revealed

    def prediction_tally(self) -> tuple[int, int]:
        """``(correct, answered)`` over the predictions made this run."""
        if self._scenario is None:
            return (0, 0)
        by_id = {d.trade_id: d for d in self._scenario.deal_stream}
        answered = correct = 0
        for trade_id, chosen in self._predictions.items():
            deal = by_id.get(trade_id)
            if deal is None or deal.prediction is None:
                continue
            if chosen == PREDICTION_SKIPPED:
                continue
            answered += 1
            correct += int(deal.prediction.is_correct(chosen))
        return (correct, answered)

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
        if outcome.realized_loss <= 0.0:
            self.default_framing.setText(
                "This default was always going to happen; it is scripted. What "
                "matters is whether you were protected. Your realized loss is 0, "
                "so you were. That is a successful underwrite, not a failure."
            )
        else:
            self.default_framing.setText(
                "This default was always going to happen; it is scripted. You were "
                "not protected, so it landed as a real loss. Collateral on this "
                "name would have prevented it."
            )
        if self._coached:
            self.default_coach.setText(step.default.coaching)
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
        self.history_table.fit_to_contents()
        self._render_skills()
        if self._coached:
            self._render_summary_verdict()
        self._record_stage_result()
        self._update_scoreboard()
        self._update_enabled()

    def _render_skills(self) -> None:
        """Grade the run skill by skill against the best play, plus predictions.

        Shown in every mode, not only guided: a bare P&L says the learner lost
        without saying which part of the job they got wrong, and that is the part
        worth carrying into the next stage.
        """
        correct, answered = self.prediction_tally()
        if answered:
            self.prediction_score.setText(
                f"Predictions: {correct} of {answered} correct."
            )
        else:
            self.prediction_score.setText("")

        if self._benchmark_score is None or self.score_result is None:
            self.skills_group.setVisible(bool(answered))
            self.skills_table.set_metrics([])
            return
        grades = coaching.skill_report(self.score_result, self._benchmark_score)
        marks = {
            coaching.GRADE_MET: "✓",
            coaching.GRADE_PARTIAL: "~",
            coaching.GRADE_MISSED: "✗",
        }
        self.skills_table.set_metrics(
            [(f"{marks.get(g.grade, '')} {g.skill}", g.detail) for g in grades]
        )
        self.skills_group.setVisible(True)

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
            csa_mpor_days=self.mpor_spin.value(),
            limit=self.limit_spin.value(),
        )

    def set_candidate(self, decision: Decision) -> None:
        """Set the decision controls from a :class:`Decision`.

        The spin boxes are filled with their signals blocked, so filling the
        whole form costs no engine runs at all; the caller asks for a preview
        once it has finished setting up. Leaving the request to the caller keeps
        this from firing a redundant second run when the caller was going to
        request one anyway.
        """
        for i, (_label, action) in enumerate(_ACTION_LABELS):
            if action == decision.action:
                self.action_combo.setCurrentIndex(i)
                break
        self.collateral_check.setChecked(decision.require_collateral)
        spins: tuple[tuple[QDoubleSpinBox | QSpinBox, float | int], ...] = (
            (self.threshold_spin, decision.csa_threshold),
            (self.mta_spin, decision.csa_mta),
            (self.im_spin, decision.csa_initial_margin),
            (self.mpor_spin, decision.csa_mpor_days),
            (self.limit_spin, decision.limit),
        )
        for spin, value in spins:
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)

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
        """Commit the decision on screen, queueing it if a preview is in flight.

        The decision is recorded immediately, because it is what the learner
        chose at the moment they committed; only the engine run is deferred. A
        commit arriving during a preview must never be dropped — moving a CSA
        dial and committing straight away is an ordinary thing to do, and the
        preview it kicked off is about to be superseded anyway.
        """
        step = self._current_step()
        if step is None or step.kind != "decision":
            return
        self._committed[step.deal.trade_id] = self._current_candidate()
        if self._thread is not None:
            self._commit_pending = True
            return
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
        # A queued commit wins over a queued preview: the learner has already
        # moved on, so re-previewing the decision they just made is wasted work.
        if self._commit_pending:
            self._commit_pending = False
            self._preview_pending = False
            self._start_run(dict(self._committed), "commit")
        elif self._preview_pending:
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
        self._preview_outcome = outcome
        # The dossier describes the counterparty, not the candidate decision, so
        # it is shown immediately — it is the evidence the learner needs *in
        # order to* decide, and withholding it behind the prediction would defeat
        # the question.
        self.dossier_table.set_metrics(self._describe_counterparty(outcome))
        self._render_consequences()

    def _render_consequences(self) -> None:
        """Draw (or withhold) the analytics for the current deal."""
        step = self._current_step()
        outcome = getattr(self, "_preview_outcome", None)
        if step is None or step.kind != "decision" or outcome is None:
            return
        if outcome.trade_id != step.deal.trade_id:
            return  # a stale preview from the previous deal
        if not self._is_revealed(step.deal):
            self.consequence_header.setText(
                "<b>Consequences</b> — hidden until you answer the question above."
            )
            self.consequence_table.set_metrics(
                [("Waiting", "Answer or skip the prediction to reveal")]
            )
            self.consequence_view.set_figure(
                simulator_profile_figure((), (), (), (), None)
            )
            self.recommendation_label.setText("")
            return

        self.consequence_header.setText("<b>Consequences before you commit</b>")
        candidate = self._current_candidate()
        limit = candidate.limit
        rows = [
            ("Peak PFE", _money(outcome.peak_pfe)),
            ("EPE", _money(outcome.epe)),
            ("Collateralized peak PFE", _money(outcome.collateralized_peak_pfe)),
        ]
        rows.extend(_collateral_rows(outcome, candidate))
        rows.extend(
            [
                ("CVA", _money(outcome.cva)),
                ("DVA", _money(outcome.dva)),
                ("BCVA", _money(outcome.bcva)),
            ]
        )
        # FVA is only shown when the scenario actually funds an uncollateralized
        # position (a non-zero funding spread); everywhere else it is a constant
        # zero and would be one more number for the learner to ignore.
        if not math.isnan(outcome.fva) and outcome.fva != 0.0:
            rows.append(("FVA", _money(outcome.fva)))
        # Netting detail is only meaningful once the client has a book to net
        # against; on a first trade it would just restate the peak PFE.
        if outcome.existing_peak_pfe > 0.0:
            rows.extend(
                [
                    (
                        "Netting set before this trade",
                        _money(outcome.existing_peak_pfe),
                    ),
                    ("Incremental exposure", _money(outcome.incremental_peak_pfe)),
                ]
            )
        rows.extend(
            [
                ("Limit", _money(limit)),
                ("Limit utilization", f"{outcome.limit_utilization:.0%}"),
                ("Headroom", _money(outcome.headroom)),
                ("Limit breach", "YES" if outcome.limit_breach else "no"),
            ]
        )
        rows.extend(_sensitivity_rows(outcome))
        self.consequence_table.set_metrics(rows)
        self.consequence_view.set_figure(
            simulator_profile_figure(
                outcome.time_grid,
                outcome.ee,
                outcome.pfe_95,
                outcome.ee_collateralized,
                limit,
            )
        )
        verdict = outcome.recommendation or "—"
        note = "" if outcome.accepted else " (this decision declines the deal)"
        self.recommendation_label.setText(
            f"Model recommendation: <b>{verdict}</b>{note}"
        )

    @staticmethod
    def _describe_counterparty(outcome: DecisionOutcome) -> list[tuple[str, str]]:
        """The credit dossier rows: what the models make of this counterparty."""
        rows: list[tuple[str, str]] = [
            ("Model grade", outcome.internal_grade or "—"),
            ("Distance to default", _fmt(outcome.distance_to_default, 2)),
            ("1y PD (Merton)", _pct(outcome.merton_pd)),
            ("Altman Z", _fmt(outcome.altman_z, 2)),
            ("Altman zone", (outcome.altman_zone or "—").title()),
            ("CDS 5y spread", _bps(outcome.cds_spread_5y)),
        ]
        # CVA per unit of exposure strips deal size out of the credit charge, so
        # two differently-sized deals can be compared on credit alone.
        if outcome.peak_pfe > 0.0 and not math.isnan(outcome.cva):
            rows.append(
                ("CVA per unit of PFE", f"{outcome.cva / outcome.peak_pfe:.2%}")
            )
        return rows

    def _apply_commit(self, result: ScenarioResult) -> None:
        self._last_result = result
        self._advance_step()

    # -- guided-mode benchmark (best play) --------------------------------- #
    def _start_benchmark(self) -> None:
        """Run the recommended-decision benchmark off-thread, if not already."""
        if self._scenario is None or self._bench_thread is not None:
            return
        decisions = coaching.recommended_decisions(self._scenario)
        if not decisions:
            return
        gen = self._bench_gen
        worker = ScenarioRunWorker(self._scenario, decisions)
        thread = create_scenario_thread(worker)
        self._bench_worker = worker
        self._bench_thread = thread
        worker.finished.connect(
            lambda result, g=gen: self._on_benchmark_ready(result, g)
        )
        thread.finished.connect(self._on_bench_thread_done)
        thread.start()

    def _on_benchmark_ready(self, result: ScenarioResult, gen: int) -> None:
        if gen != self._bench_gen:
            return  # a newer scenario was loaded; discard this stale run
        self._benchmark_result = result
        self._benchmark_score = score_scenario(result)
        self._update_on_track()
        step = self._current_step()
        if step is not None and step.kind == "end":
            # The run finished before its benchmark landed: fill in the parts
            # that needed the reference now that it is here.
            self._render_skills()
            if self._coached:
                self._render_summary_verdict()
            self._record_stage_result()
        self.benchmarkReady.emit()

    def _on_bench_thread_done(self) -> None:
        self._bench_thread = None
        self._bench_worker = None

    def is_benchmark_ready(self) -> bool:
        """Whether the best-play benchmark has finished (for tests)."""
        return self._benchmark_score is not None

    # -- coach panel ------------------------------------------------------- #
    def _apply_recommended(self) -> None:
        """Fill the decision controls from the deal's recommended decision."""
        step = self._current_step()
        if (
            not self._coached
            or step is None
            or step.kind != "decision"
            or step.deal is None
            or step.deal.recommended is None
        ):
            return
        # set_candidate fills the controls silently, so ask for the one preview
        # that reflects the whole recommended decision.
        self.set_candidate(step.deal.recommended)
        self._ensure_preview()

    def _update_coach_panel(self, step: PlayStep) -> None:
        deal = step.deal
        assert deal is not None
        self.coach_text.setText(deal.coaching or "No coaching notes for this deal.")
        if deal.recommended is not None:
            self.coach_reco.setText(self._recommended_summary(deal.recommended))
        else:
            self.coach_reco.setText("")
        self._update_on_track()

    @staticmethod
    def _recommended_summary(decision: Decision) -> str:
        action = {
            DecisionAction.APPROVE: "Approve",
            DecisionAction.CONDITION: "Condition (collateralize)",
            DecisionAction.DECLINE: "Decline",
        }[decision.action]
        collateral = (
            "require collateral" if decision.require_collateral else "no collateral"
        )
        return (
            f"Recommended: <b>{action}</b>, {collateral}, limit {decision.limit:,.0f}."
        )

    def _update_on_track(self) -> None:
        if not self._coached:
            self.on_track_label.setText("")
            return
        if self._benchmark_score is None:
            self.on_track_label.setText("Versus best play: computing benchmark…")
            return
        step = self._current_step()
        if step is None:
            return
        # Compare only rounds the learner has actually completed, so the gauge is
        # like-for-like (the current, undecided round is excluded from both).
        completed = step.round - 1
        if completed < 0:
            self.on_track_label.setText(
                "Versus best play: play your first round to see your pace."
            )
            return
        student_net = coaching.cumulative_net(self._live_score(), completed)
        bench_net = coaching.cumulative_net(self._benchmark_score, completed)
        self.on_track_label.setText(
            f"Versus best play: {coaching.on_track_label(student_net, bench_net)}."
        )

    def _render_summary_verdict(self) -> None:
        if not self._coached or self._scenario is None:
            return
        self.outro_label.setText(self._scenario.meta.outro)
        if self._benchmark_result is None or self._benchmark_score is None:
            self.verdict_headline.setText(
                "Scoring against best play… (computing the benchmark run)."
            )
            self.verdict_notes.setText("")
            return
        student_result = self._last_result or ScenarioResult()
        verdict = coaching.evaluate(
            self._scenario, student_result, self._benchmark_result
        )
        self.verdict_headline.setText(f"<b>{verdict.band}.</b> {verdict.headline}")
        if verdict.notes:
            items = "".join(f"<li>{n}</li>" for n in verdict.notes)
            self.verdict_notes.setText(f"<ul>{items}</ul>")
        else:
            self.verdict_notes.setText("You matched the best play round for round.")

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
        has_reco = (
            is_decision and step.deal is not None and step.deal.recommended is not None
        )
        self.apply_reco_btn.setEnabled(self._coached and has_reco and not busy)
        # The prediction stays answerable while a preview is in flight — it is
        # about what the learner expects, not about what the engine returned.
        unanswered = (
            is_decision
            and step.deal is not None
            and step.deal.prediction is not None
            and step.deal.trade_id not in self._predictions
        )
        self.answer_btn.setEnabled(unanswered)
        self.skip_prediction_btn.setEnabled(unanswered)

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
        intro = f"<p><i>{meta.intro}</i></p>" if self._coached and meta.intro else ""
        stage = (
            self.campaign.stage(self._stage_name)
            if self._stage_name is not None
            else None
        )
        header = f"<h3>{meta.title}</h3>"
        if stage is not None:
            idx = self.campaign.index_of(stage.scenario_name) + 1
            header = (
                f"<p><b>Campaign stage {idx} of {len(self.campaign)}</b> — "
                f"clears at {stage.pass_ratio:.0%} of the best play</p>" + header
            )
        self._set_framing(
            header
            + f"<p>{meta.description}</p>"
            + f"<p><b>{meta.n_rounds} rounds.</b> Counterparties: {names}.</p>"
            + (f"<ul>{objectives}</ul>" if objectives else "")
            + intro
        )

    def _show_prompt(self) -> None:
        self.stack.setCurrentWidget(self._prompt_page)
        self._set_framing(
            "<h3>Underwriting simulator</h3>"
            "<p>Load a scenario to begin. The bundled sample walks through rising "
            "rates and a counterparty that deteriorates and defaults.</p>"
        )


def headless_score(scenario: Scenario, decisions: dict[str, Decision]) -> ScoreResult:
    """Score a full scripted play headlessly — the reference the tab must match."""
    return Scorer().score(ScenarioEngine(scenario).run(decisions))
