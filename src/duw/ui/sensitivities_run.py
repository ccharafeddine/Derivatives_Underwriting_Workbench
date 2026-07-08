"""Run the sensitivities finite-difference off the UI thread.

:func:`compute_sensitivities` runs four pipelines, so it must not block the
interface. This wraps it in a daemon thread and delivers the
:class:`~duw.risk.sensitivities.Sensitivities` (or ``None`` on error) via a
queued Qt signal.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from duw.domain.counterparty import Counterparty
from duw.domain.instruments import NettingSet, Trade
from duw.domain.market import MarketSnapshot
from duw.pipeline.orchestrator import RunConfig
from duw.risk.sensitivities import Sensitivities, compute_sensitivities


class _SensSignals(QObject):
    finished = Signal(object)  # Sensitivities | None


def compute_async(
    counterparty: Counterparty,
    netting_set: NettingSet,
    proposed_trade: Trade,
    config: RunConfig,
    snapshot: MarketSnapshot,
    on_result: Callable[[Sensitivities | None], None],
) -> QObject:
    """Compute sensitivities in a daemon thread; call ``on_result`` on the UI thread."""
    signals = _SensSignals()
    signals.finished.connect(on_result)

    def work() -> None:
        try:
            result: Sensitivities | None = compute_sensitivities(
                counterparty, netting_set, proposed_trade, config, snapshot
            )
        except Exception:  # noqa: BLE001 - surface any failure as a graceful None
            result = None
        signals.finished.emit(result)

    threading.Thread(target=work, daemon=True).start()
    return signals
