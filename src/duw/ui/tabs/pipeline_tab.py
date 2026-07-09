"""Deal pipeline tab.

A board of saved underwriting deals, one column per approval stage. A deal can
be moved between stages, reopened (which re-runs its saved inputs to repopulate
the analytics tabs), or deleted. The heavy lifting lives in
:mod:`duw.store.deals`; this tab is presentation plus a reopen signal.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from duw.store.deals import STAGES, Deal, DealStore

_DEAL_ID_ROLE = Qt.ItemDataRole.UserRole


class PipelineTab(QWidget):
    """Kanban-style board over a :class:`DealStore`."""

    reopenRequested = Signal(object)  # Deal

    def __init__(self, store: DealStore) -> None:
        super().__init__()
        self.store = store
        self._columns: dict[str, QListWidget] = {}

        self.intro = QLabel(
            "<b>Deal pipeline.</b> Deals you save land here as a board, one column "
            "per approval stage. To add one: run an analysis (Run Analysis), then "
            "save it with <b>File → Save Deal</b> (Ctrl+S). Select a deal to move it "
            "between stages, <b>Reopen</b> it to reload its saved analysis into the "
            "other tabs, or delete it."
        )
        self.intro.setWordWrap(True)

        self.empty_hint = QLabel(
            "No saved deals yet — run an analysis and choose File → Save Deal to add "
            "your first one."
        )
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.setStyleSheet("padding:24px; font-size:14px;")

        board = QHBoxLayout()
        for stage in STAGES:
            box = QGroupBox(stage.value)
            col_layout = QVBoxLayout(box)
            listw = QListWidget()
            listw.itemSelectionChanged.connect(lambda s=stage: self._on_selection(s))
            col_layout.addWidget(listw)
            self._columns[stage.value] = listw
            board.addWidget(box)

        self.move_left_btn = QPushButton("◀ Move back")
        self.move_right_btn = QPushButton("Move forward ▶")
        self.reopen_btn = QPushButton("Reopen")
        self.delete_btn = QPushButton("Delete")
        self.refresh_btn = QPushButton("Refresh")
        self.move_left_btn.clicked.connect(lambda: self._move(-1))
        self.move_right_btn.clicked.connect(lambda: self._move(+1))
        self.reopen_btn.clicked.connect(self._reopen)
        self.delete_btn.clicked.connect(self._delete)
        self.refresh_btn.clicked.connect(self.refresh)

        controls = QHBoxLayout()
        for btn in (
            self.move_left_btn,
            self.move_right_btn,
            self.reopen_btn,
            self.delete_btn,
        ):
            btn.setEnabled(False)
            controls.addWidget(btn)
        controls.addStretch(1)
        controls.addWidget(self.refresh_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self.intro)
        layout.addWidget(self.empty_hint)
        layout.addLayout(controls)
        layout.addLayout(board)

        self.refresh()

    # -- data -------------------------------------------------------------- #
    def refresh(self) -> None:
        """Reload deals from the store into their stage columns."""
        for listw in self._columns.values():
            listw.clear()
        deals = self.store.list()
        for deal in deals:
            listw = self._columns.get(deal.stage.value)
            if listw is None:
                continue
            item = QListWidgetItem(self._label(deal))
            item.setData(_DEAL_ID_ROLE, deal.deal_id)
            listw.addItem(item)
        # Show the "how to add a deal" hint only while the board is empty.
        self.empty_hint.setVisible(not deals)
        self._update_buttons()

    @staticmethod
    def _label(deal: Deal) -> str:
        s = deal.summary
        rec = s.get("recommendation") or "—"
        cp = s.get("counterparty") or ""
        product = s.get("product") or ""
        return f"{deal.name}\n{product} · {cp}\n{rec}"

    def add_deal(self, deal: Deal) -> None:
        """Persist a deal and refresh the board."""
        self.store.save(deal)
        self.refresh()

    # -- selection --------------------------------------------------------- #
    def _on_selection(self, stage) -> None:
        # Keep a single selection across all columns.
        for value, listw in self._columns.items():
            if value != stage.value:
                listw.blockSignals(True)
                listw.clearSelection()
                listw.setCurrentItem(None)
                listw.blockSignals(False)
        self._update_buttons()

    def _selected(self) -> tuple[str, int] | None:
        for idx, stage in enumerate(STAGES):
            listw = self._columns[stage.value]
            item = listw.currentItem()
            if item is not None and item.isSelected():
                return item.data(_DEAL_ID_ROLE), idx
        return None

    def selected_deal(self) -> Deal | None:
        """Return the currently selected deal, if any."""
        sel = self._selected()
        return self.store.get(sel[0]) if sel is not None else None

    def _update_buttons(self) -> None:
        sel = self._selected()
        has = sel is not None
        idx = sel[1] if sel is not None else -1
        self.reopen_btn.setEnabled(has)
        self.delete_btn.setEnabled(has)
        self.move_left_btn.setEnabled(has and idx > 0)
        self.move_right_btn.setEnabled(has and 0 <= idx < len(STAGES) - 1)

    # -- actions ----------------------------------------------------------- #
    def _move(self, delta: int) -> None:
        sel = self._selected()
        if sel is None:
            return
        deal_id, idx = sel
        new_idx = idx + delta
        if 0 <= new_idx < len(STAGES):
            self.store.update_stage(deal_id, STAGES[new_idx])
            self.refresh()

    def _reopen(self) -> None:
        deal = self.selected_deal()
        if deal is not None:
            self.reopenRequested.emit(deal)

    def _delete(self) -> None:
        sel = self._selected()
        if sel is not None:
            self.store.delete(sel[0])
            self.refresh()
