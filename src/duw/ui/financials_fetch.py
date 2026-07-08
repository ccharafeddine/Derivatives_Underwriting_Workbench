"""Run the public-financials fetch off the UI thread.

Wraps :func:`duw.credit.public_data.fetch_financials` (yfinance, offline-safe) in
a background thread and delivers the result on the UI thread via a queued Qt
signal, so a network fetch never blocks the interface. The result is a
:class:`~duw.domain.counterparty.Financials` or ``None`` on any failure.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from duw.credit.public_data import fetch_financials
from duw.domain.counterparty import Financials


class _FetchSignals(QObject):
    finished = Signal(object)  # Financials | None


def fetch_async(
    ticker: str,
    equity_volatility: float,
    currency: str,
    on_result: Callable[[Financials | None], None],
) -> QObject:
    """Fetch financials for ``ticker`` in a daemon thread; call ``on_result``.

    Returns the signalling object; the caller keeps a reference alive until the
    result arrives.
    """
    signals = _FetchSignals()
    signals.finished.connect(on_result)

    def work() -> None:
        signals.finished.emit(
            fetch_financials(
                ticker, equity_volatility=equity_volatility, currency=currency
            )
        )

    threading.Thread(target=work, daemon=True).start()
    return signals
