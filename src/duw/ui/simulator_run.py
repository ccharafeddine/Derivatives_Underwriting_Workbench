"""Run the scenario engine off the UI thread.

Stepping a scenario runs the underwriting pipeline once per deal, so it must not
block the interface. This wraps :class:`~duw.scenario.engine.ScenarioEngine` in a
:class:`QObject` with Qt signals and moves it onto a fresh :class:`QThread`,
mirroring :mod:`duw.pipeline.worker`. The engine itself stays pure; this is the
only scenario-facing module that imports Qt.

The worker emits ``finished(ScenarioResult)`` or ``failed(message)``; exceptions
never escape the thread. The caller keeps the returned thread and worker alive
until the run completes.
"""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import QObject, QThread, Signal

from duw.domain.market import MarketSnapshot
from duw.scenario.engine import ScenarioEngine
from duw.scenario.model import Decision, Scenario


class ScenarioRunWorker(QObject):
    """Runs one full scenario pass off-thread, reporting via signals."""

    finished = Signal(object)  # ScenarioResult
    failed = Signal(str)

    def __init__(
        self,
        scenario: Scenario,
        decisions: Mapping[str, Decision],
        base_snapshot: MarketSnapshot | None = None,
    ) -> None:
        super().__init__()
        self._scenario = scenario
        self._decisions = dict(decisions)
        self._base_snapshot = base_snapshot

    def run(self) -> None:
        """Execute the scenario. Intended to run on a worker thread."""
        try:
            engine = ScenarioEngine(self._scenario, base_snapshot=self._base_snapshot)
            result = engine.run(self._decisions)
            self.finished.emit(result)
        except Exception as exc:  # deliver failures on the signal, never raise
            self.failed.emit(str(exc))


def create_scenario_thread(worker: ScenarioRunWorker) -> QThread:
    """Move ``worker`` onto a fresh :class:`QThread` and wire its lifecycle.

    Starting the returned thread invokes :meth:`ScenarioRunWorker.run`; the
    thread quits when the worker finishes or fails.
    """
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    return thread
