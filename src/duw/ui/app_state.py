"""Shared UI application state.

A small :class:`QObject` that the input tabs read from and write to, so the
main window can react to changes (e.g. enabling the Run action) without the tabs
knowing about each other. Holds the loaded market snapshot and seed
counterparties (offline), the currently selected counterparty, the proposed
trade, and the **book** of existing trades that the proposed trade nets against.

Qt lives here (this is the ``ui`` package). No analytics: this module only
carries state and emits change signals.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from duw.data.loader import load_market_snapshot, load_seed_counterparties
from duw.domain.counterparty import Counterparty
from duw.domain.instruments import NettingSet, Trade
from duw.domain.market import MarketSnapshot


class AppState(QObject):
    """Holds the current underwriting inputs and notifies on change."""

    tradeChanged = Signal(object)  # Trade | None
    counterpartyChanged = Signal(object)  # Counterparty | None
    bookChanged = Signal()
    snapshotChanged = Signal()

    def __init__(self, snapshot: MarketSnapshot | None = None) -> None:
        super().__init__()
        self.snapshot: MarketSnapshot = snapshot or load_market_snapshot()
        self.counterparties: list[Counterparty] = load_seed_counterparties()
        self.trade: Trade | None = None
        self.counterparty: Counterparty | None = None
        self.book: list[Trade] = []

    # -- proposed trade / counterparty ------------------------------------- #
    def set_trade(self, trade: Trade | None) -> None:
        """Set (or clear) the proposed trade and notify listeners."""
        self.trade = trade
        self.tradeChanged.emit(trade)

    def set_counterparty(self, counterparty: Counterparty | None) -> None:
        """Set (or clear) the selected counterparty and notify listeners."""
        self.counterparty = counterparty
        self.counterpartyChanged.emit(counterparty)

    # -- existing-trades book ---------------------------------------------- #
    @property
    def existing_set(self) -> NettingSet:
        """The counterparty's book of existing trades as a netting set."""
        cid = self.counterparty.counterparty_id if self.counterparty else ""
        return NettingSet(
            netting_set_id=f"NS-{cid}" if cid else "NS",
            counterparty_id=cid,
            trades=tuple(self.book),
        )

    def add_to_book(self, trade: Trade) -> None:
        """Add an existing trade to the book."""
        self.book.append(trade)
        self.bookChanged.emit()

    def remove_from_book(self, index: int) -> None:
        """Remove the book trade at ``index`` (no-op if out of range)."""
        if 0 <= index < len(self.book):
            del self.book[index]
            self.bookChanged.emit()

    def clear_book(self) -> None:
        """Empty the book."""
        if self.book:
            self.book.clear()
            self.bookChanged.emit()

    # -- market snapshot (editable working copy) --------------------------- #
    def set_snapshot(self, snapshot: MarketSnapshot) -> None:
        """Replace the working market snapshot and notify listeners."""
        self.snapshot = snapshot
        self.snapshotChanged.emit()

    def reset_snapshot(self) -> None:
        """Reload the bundled market snapshot, discarding any edits."""
        self.set_snapshot(load_market_snapshot())

    # -- run readiness ----------------------------------------------------- #
    def is_ready(self) -> bool:
        """Whether both a valid trade and counterparty are selected."""
        return self.trade is not None and self.counterparty is not None

    def run_inputs(self) -> tuple[Counterparty, NettingSet, Trade]:
        """Return ``(counterparty, existing_set, proposed_trade)`` for a run.

        Raises :class:`ValueError` if inputs are incomplete.
        """
        if self.counterparty is None or self.trade is None:
            raise ValueError("both a counterparty and a trade are required")
        return self.counterparty, self.existing_set, self.trade
