"""App-shell widgets for the Graphite layout.

- :class:`TopBar`: the persistent deal header. Brand, the deal in context
  (counterparty, proposed trade, existing book, market snapshot) as clickable
  chips, and the main actions.
- :class:`NavPanel`: grouped left navigation that replaces the row of tabs.
- :class:`PageHeader`: page title and one-line subtitle.
- :class:`KpiStrip`: hairline-divided headline numbers for the current deal.
- :class:`Panel`: a titled, hairline-bordered section (title bar, body, note).
- :class:`LimitBar`: existing vs proposed exposure against a limit.

All styling comes from :func:`duw.ui.theme.stylesheet` via object names; the
only colours read here are tone colours (gain / loss / breach) from the active
theme's tokens. Same structure as Portfolio Analyzer's ``app_shell``.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from duw.ui import theme

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def logo_path(name: str = "logo.svg") -> str:
    """Path to a bundled logo asset (``logo.svg``, ``logo_mark.svg``, ...)."""
    return str(ASSETS / name)


def app_icon() -> QIcon:
    """The application icon (the unified finance-apps Workbench tile)."""
    icon = QIcon()
    path = ASSETS / "logo.svg"
    if path.exists():
        for size in (16, 24, 32, 48, 64, 128, 256):
            icon.addFile(str(path), QSize(size, size))
    return icon


# --------------------------------------------------------------------------- #
# Top bar (persistent deal header)
# --------------------------------------------------------------------------- #
class TopBar(QFrame):
    """Brand, deal context chips and the primary actions."""

    pageRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("topBar")
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 6, 10, 6)
        row.setSpacing(8)

        mark = QLabel()
        mark.setPixmap(QIcon(logo_path("logo.svg")).pixmap(20, 20))
        row.addWidget(mark)
        brand = QLabel("UNDERWRITING WORKBENCH")
        brand.setObjectName("brand")
        row.addWidget(brand)
        row.addSpacing(16)

        self.chip_counterparty = self._chip("No counterparty", "Counterparty")
        self.chip_trade = self._chip("No trade", "Trade")
        self.chip_book = self._chip("Book: none", "Trade")
        for chip in (self.chip_counterparty, self.chip_trade, self.chip_book):
            row.addWidget(chip)
        self.snapshot_label = QLabel("")
        self.snapshot_label.setObjectName("ctxLabel")
        row.addSpacing(6)
        row.addWidget(self.snapshot_label)
        row.addStretch(1)

        self.example_tag = QLabel("EXAMPLE DATA")
        self.example_tag.setObjectName("exampleTag")
        self.example_tag.setVisible(False)
        row.addWidget(self.example_tag)
        self.examples_button = QToolButton()
        self.examples_button.setObjectName("ghostTool")
        self.examples_button.setText("Examples")
        self.examples_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.examples_button.setToolTip("Load a preconfigured example deal")
        row.addWidget(self.examples_button)
        self.save_button = QPushButton("Save deal")
        self.save_button.setObjectName("ghost")
        self.save_button.setToolTip("Save this deal to the pipeline (Ctrl+S)")
        row.addWidget(self.save_button)
        self.run_button = QPushButton("Run analysis")
        self.run_button.setObjectName("primary")
        self.run_button.setToolTip(
            "Run the full underwriting analysis on the current trade and "
            "counterparty (Ctrl+R)."
        )
        row.addWidget(self.run_button)
        for b in (self.examples_button, self.save_button, self.run_button):
            b.setCursor(Qt.CursorShape.PointingHandCursor)

    def _chip(self, text: str, page: str) -> QToolButton:
        chip = QToolButton()
        chip.setObjectName("ctxChip")
        chip.setText(text)
        chip.setToolTip(f"Open {page}")
        chip.setCursor(Qt.CursorShape.PointingHandCursor)
        chip.clicked.connect(lambda: self.pageRequested.emit(page))
        return chip

    def set_context(
        self, counterparty: str, trade: str, book: str, snapshot: str
    ) -> None:
        for chip, text, width in (
            (self.chip_counterparty, counterparty, 180),
            (self.chip_trade, trade, 240),
            (self.chip_book, book, 100),
        ):
            # Elide long names so the header fits a 1366-px laptop screen.
            metrics = chip.fontMetrics()
            chip.setText(metrics.elidedText(text, Qt.TextElideMode.ElideRight, width))
            chip.setToolTip(text)
        self.snapshot_label.setText(snapshot)

    def set_example(self, name: str | None) -> None:
        self.example_tag.setVisible(bool(name))
        self.example_tag.setToolTip(f"Loaded example: {name}" if name else "")

    def set_running(self, running: bool) -> None:
        self.run_button.setText("Running…" if running else "Run analysis")


# --------------------------------------------------------------------------- #
# Navigation
# --------------------------------------------------------------------------- #
# (group, [(display label, page key)]). Page keys are the workflow names in
# ``main_window.TAB_NAMES`` (also the help-registry keys).
NAV_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Deal",
        [
            ("Overview", "Overview"),
            ("Trade ticket", "Trade"),
            ("Counterparty", "Counterparty"),
        ],
    ),
    (
        "Analytics",
        [
            ("Exposure", "Exposure"),
            ("Limits", "Limits"),
            ("Collateral & CSA", "Collateral"),
            ("XVA", "CVA"),
            ("Stress & scenarios", "Scenario"),
            ("Sensitivities", "Sensitivities"),
        ],
    ),
    ("Market", [("Curves & credit", "Market")]),
    (
        "Output",
        [
            ("Credit memo", "Memo"),
            ("Deal pipeline", "Pipeline"),
            ("Training simulator", "Simulator"),
        ],
    ),
]

_ROLE_KEY = Qt.ItemDataRole.UserRole + 1


class NavPanel(QFrame):
    """Grouped navigation list; emits ``pageSelected(key)``."""

    pageSelected = Signal(str)
    WIDTH = 196

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("navPanel")
        self.setFixedWidth(self.WIDTH)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 8, 0, 8)
        self.list = QListWidget()
        self.list.setObjectName("navList")
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lay.addWidget(self.list)
        self._items: dict[str, QListWidgetItem] = {}
        self._headers: list[QListWidgetItem] = []
        for group, entries in NAV_GROUPS:
            head = QListWidgetItem(group.upper())
            head.setFlags(Qt.ItemFlag.NoItemFlags)
            font = head.font()
            font.setPointSizeF(max(6.5, font.pointSizeF() * 0.78))
            font.setBold(True)
            head.setFont(font)
            head.setSizeHint(QSize(0, 28))
            self._headers.append(head)
            self.list.addItem(head)
            for label, key in entries:
                item = QListWidgetItem(label)
                item.setData(_ROLE_KEY, key)
                self.list.addItem(item)
                self._items[key] = item
        self.retheme()
        self._current = "Overview"
        self.list.currentItemChanged.connect(lambda cur, _prev: self._on_item(cur))
        self.select("Overview")

    def keys(self) -> list[str]:
        return list(self._items)

    def label(self, key: str) -> str:
        item = self._items.get(key)
        return item.text() if item is not None else key

    def _on_item(self, item: QListWidgetItem | None) -> None:
        if item is None or not item.data(_ROLE_KEY):
            return
        self._current = item.data(_ROLE_KEY)
        self.pageSelected.emit(self._current)

    def select(self, key: str) -> None:
        """Highlight ``key`` without emitting ``pageSelected``."""
        item = self._items.get(key)
        if item is None:
            return
        self._current = key
        self.list.blockSignals(True)
        self.list.setCurrentItem(item)
        self.list.blockSignals(False)

    def current(self) -> str:
        return self._current

    def retheme(self) -> None:
        muted = QColor(theme.tokens()["text_faint"])
        for head in self._headers:
            head.setForeground(muted)


# --------------------------------------------------------------------------- #
# Page header and KPI strip
# --------------------------------------------------------------------------- #
class PageHeader(QFrame):
    """``Title  subtitle`` on one baseline."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageHeader")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        self.title = QLabel("")
        self.title.setObjectName("pageTitle")
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("pageSub")
        row.addWidget(self.title, 0, Qt.AlignmentFlag.AlignBaseline)
        row.addWidget(self.subtitle, 1, Qt.AlignmentFlag.AlignBaseline)

    def set_page(self, title: str, subtitle: str) -> None:
        self.title.setText(title)
        self.subtitle.setText(subtitle)


class KpiCell(QFrame):
    """One headline number: small-caps label, value, sub-line."""

    def __init__(self, label: str) -> None:
        super().__init__()
        self.setObjectName("kpiCell")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 7, 12, 7)
        lay.setSpacing(1)
        self.label = QLabel(label.upper())
        self.label.setObjectName("kpiLabel")
        self.value = QLabel("—")
        self.value.setObjectName("kpiValue")
        self.sub = QLabel(" ")
        self.sub.setObjectName("kpiSub")
        for w in (self.label, self.value, self.sub):
            lay.addWidget(w)

    def set(self, value: str, sub: str = "", tone: str | None = None) -> None:
        self.value.setText(value)
        self.sub.setText(sub or " ")
        t = theme.tokens()
        color = {"pos": t["green"], "neg": t["red"], "warn": t["amber"]}.get(tone or "")
        self.value.setStyleSheet(f"color: {color};" if color else "")


class KpiStrip(QFrame):
    """Headline deal numbers. ``set_metric(name, value, sub, tone)``."""

    NAMES = (
        "Peak PFE 95%",
        "Limit use",
        "EPE",
        "CVA",
        "DVA",
        "FVA",
        "MtM today",
        "Recommendation",
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("kpiStrip")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._cells: dict[str, KpiCell] = {}
        for name in self.NAMES:
            cell = KpiCell(name)
            self._cells[name] = cell
            lay.addWidget(cell, 1)
        self.clear()

    def cell(self, name: str) -> KpiCell:
        return self._cells[name]

    def set_metric(
        self, name: str, value: str, sub: str = "", tone: str | None = None
    ) -> None:
        if name in self._cells:
            self._cells[name].set(value, sub, tone)

    def clear(self) -> None:
        for cell in self._cells.values():
            cell.set("—")


# --------------------------------------------------------------------------- #
# Panels
# --------------------------------------------------------------------------- #
class Panel(QFrame):
    """Titled section: ``TITLE ........ aside`` bar, a body, optional note."""

    def __init__(
        self, title: str, aside: str = "", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        bar = QWidget()
        bar_row = QHBoxLayout(bar)
        bar_row.setContentsMargins(0, 0, 0, 0)
        bar_row.setSpacing(0)
        self.title_label = QLabel(title.upper())
        self.title_label.setObjectName("panelTitle")
        self.aside_label = QLabel(aside)
        self.aside_label.setObjectName("panelTitle")
        self.aside_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        bar_row.addWidget(self.title_label)
        bar_row.addWidget(self.aside_label, 1)
        outer.addWidget(bar)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(0)
        outer.addLayout(self.body, 1)
        self.note = QLabel("")
        self.note.setObjectName("panelNote")
        self.note.setWordWrap(True)
        self.note.setVisible(False)
        outer.addWidget(self.note)

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self.body.addWidget(widget, stretch)
        return widget

    def set_aside(self, text: str) -> None:
        self.aside_label.setText(text)

    def set_note(self, text: str) -> None:
        self.note.setText(text)
        self.note.setVisible(bool(text))


class LimitBar(QWidget):
    """Existing and proposed exposure against a limit, with an early-warning tick."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(22)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.existing = 0.0
        self.proposed = 0.0
        self.limit = 0.0
        self.warn_at = 0.85

    def set_values(self, existing: float, proposed: float, limit: float) -> None:
        self.existing = max(existing, 0.0)
        self.proposed = max(proposed, 0.0)
        self.limit = max(limit, 0.0)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        t = theme.tokens()
        p = QPainter(self)
        w, h = self.width(), 10.0
        y = (self.height() - h) / 2.0
        p.fillRect(QRectF(0, y, w, h), QColor(t["raised"]))
        if self.limit > 0:
            scale = w / max(self.limit, self.existing + self.proposed)
            ex = self.existing * scale
            pr = self.proposed * scale
            breach = self.existing + self.proposed > self.limit
            p.fillRect(QRectF(0, y, ex, h), QColor(t["text_muted"]))
            p.fillRect(
                QRectF(ex, y, pr, h), QColor(t["red"] if breach else t["accent_soft"])
            )
            for frac, color in ((self.warn_at, t["amber"]), (1.0, t["text_slate"])):
                x = min(w - 2, self.limit * frac * scale)
                p.fillRect(QRectF(x, y - 3, 2, h + 6), QColor(color))
        p.end()


def tinted_pixmap(svg: str, size: int) -> QPixmap:
    """Render a bundled SVG at ``size`` px (for labels)."""
    return QIcon(logo_path(svg)).pixmap(size, size)
