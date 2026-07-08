"""Shared UI application state.

A small :class:`QObject` that the input tabs read from and write to, so the
main window can react to changes (e.g. enabling the Run action) without the tabs
knowing about each other. Holds the loaded market snapshot and seed
counterparties (offline), the currently selected counterparty and proposed
trade, and the counterparty's existing netting set.

Qt lives here (this is the ``ui`` package). No analytics: this module only
carries state and emits change signals.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from duw.data.loader import load_market_snapshot, load_seed_counterparties
from duw.domain.counterparty import Counterparty
from duw.domain.instruments import NettingSet, Trade
from duw.domain.market import MarketSnapshot


def _empty_netting_set(counterparty_id: str = "") -> NettingSet:
    return NettingSet(
        netting_set_id=f"NS-{counterparty_id}" if counterparty_id else "NS",
        counterparty_id=counterparty_id,
        trades=(),
    )


class AppState(QObject):
    """Holds the current underwriting inputs and notifies on change."""

    tradeChanged = Signal(object)  # Trade | None
    counterpartyChanged = Signal(object)  # Counterparty | None

    def __init__(self, snapshot: MarketSnapshot | None = None) -> None:
        super().__init__()
        self.snapshot: MarketSnapshot = snapshot or load_market_snapshot()
        self.counterparties: list[Counterparty] = load_seed_counterparties()
        self.trade: Trade | None = None
        self.counterparty: Counterparty | None = None
        self.existing_set: NettingSet = _empty_netting_set()

    def set_trade(self, trade: Trade | None) -> None:
        """Set (or clear) the proposed trade and notify listeners."""
        self.trade = trade
        self.tradeChanged.emit(trade)

    def set_counterparty(self, counterparty: Counterparty | None) -> None:
        """Set (or clear) the selected counterparty and notify listeners."""
        self.counterparty = counterparty
        self.existing_set = _empty_netting_set(
            counterparty.counterparty_id if counterparty else ""
        )
        self.counterpartyChanged.emit(counterparty)

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
