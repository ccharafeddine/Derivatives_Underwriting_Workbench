"""Background worker.

Wraps the :class:`Orchestrator` in a :class:`QObject` with Qt signals so the UI
can run an underwriting pipeline off the main thread and stay responsive. This
is the only module in ``duw.pipeline`` that imports Qt.

Typical use from the UI::

    worker = PipelineWorker(counterparty, existing_set, proposed_trade, config)
    thread = create_worker_thread(worker)
    worker.progress.connect(progress_bar.set_fraction)
    worker.finished.connect(on_results)
    worker.failed.connect(on_error)
    thread.start()

The worker emits ``progress(fraction, message)`` per step, then either
``finished(AnalysisResults)`` or ``failed(message)``. Exceptions never escape the
thread; they are delivered on ``failed``.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from duw.domain.counterparty import Counterparty
from duw.domain.instruments import NettingSet, Trade
from duw.domain.market import MarketSnapshot
from duw.pipeline.orchestrator import Orchestrator, RunConfig


class PipelineWorker(QObject):
    """Runs the orchestrator off-thread, reporting progress via signals."""

    progress = Signal(float, str)
    finished = Signal(object)  # AnalysisResults
    failed = Signal(str)

    def __init__(
        self,
        counterparty: Counterparty,
        existing_set: NettingSet,
        proposed_trade: Trade,
        config: RunConfig | None = None,
        *,
        snapshot: MarketSnapshot | None = None,
        output_dir: str | Path | None = None,
    ) -> None:
        super().__init__()
        self._counterparty = counterparty
        self._existing_set = existing_set
        self._proposed_trade = proposed_trade
        self._config = config or RunConfig()
        self._snapshot = snapshot
        self._output_dir = output_dir

    def run(self) -> None:
        """Execute the pipeline. Intended to be invoked on a worker thread."""
        try:
            orchestrator = Orchestrator(
                self._config, progress_callback=self._on_progress
            )
            results = orchestrator.run(
                self._counterparty,
                self._existing_set,
                self._proposed_trade,
                snapshot=self._snapshot,
                output_dir=self._output_dir,
            )
            self.finished.emit(results)
        except Exception as exc:  # deliver failures on the signal, never raise
            self.failed.emit(str(exc))

    def _on_progress(self, fraction: float, message: str) -> None:
        self.progress.emit(fraction, message)


def create_worker_thread(worker: PipelineWorker) -> QThread:
    """Move ``worker`` onto a fresh :class:`QThread` and wire its lifecycle.

    Starting the returned thread invokes :meth:`PipelineWorker.run`; the thread
    quits when the worker finishes or fails. The caller keeps a reference to the
    returned thread (and the worker) alive until it completes.
    """
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    return thread
