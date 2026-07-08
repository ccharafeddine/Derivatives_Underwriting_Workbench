"""Run the update check off the UI thread.

Wraps :func:`duw.updates.check_for_updates` in a background thread and delivers
the :class:`~duw.updates.UpdateInfo` back on the UI thread via a queued Qt
signal, so the network call never blocks the interface.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from duw.updates import UpdateInfo, check_for_updates


class _UpdateSignals(QObject):
    finished = Signal(object)  # UpdateInfo


def check_async(on_result: Callable[[UpdateInfo], None]) -> QObject:
    """Run the update check in a daemon thread; call ``on_result`` on the UI thread.

    Returns the signalling object; the caller must keep a reference to it alive
    until the result arrives (e.g. store it on the window).
    """
    signals = _UpdateSignals()
    signals.finished.connect(on_result)

    def work() -> None:
        signals.finished.emit(check_for_updates())

    threading.Thread(target=work, daemon=True).start()
    return signals
