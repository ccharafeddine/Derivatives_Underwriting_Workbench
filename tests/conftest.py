"""Shared pytest fixtures.

Provides a session-scoped ``QApplication`` for Qt widget tests. Qt tests must
run headlessly; set ``QT_QPA_PLATFORM=offscreen`` in the environment when
invoking pytest.

Also isolates the campaign progress file from the machine running the tests: a
``SimulatorTab`` built without an explicit store defaults to the learner's real
``~/.duw/campaign.json``, and playing a bundled scenario that happens to be a
campaign stage records a result there. Left alone, running the suite would mark
stages cleared on the developer's own account.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from duw.store import progress as progress_module  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """Return the process-wide QApplication, creating it if needed."""
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def join_worker_threads(monkeypatch):
    """Let every QThread a test started finish before the test ends.

    The Simulator and main window run the pipeline on a fresh ``QThread``. A
    test that triggers a run and returns lets its widget (and the thread it
    owns) be destroyed while the thread is still working, or leaves it running
    into interpreter shutdown. Qt then aborts ("QThread: Destroyed while thread
    is still running") or Python dies in final GC (bool_dealloc / segfault),
    after every test has already passed.
    """
    import duw.ui.main_window as main_window
    import duw.ui.tabs.simulator_tab as simulator_tab

    started: list = []

    def tracking(factory):
        def wrapper(worker):
            thread = factory(worker)
            started.append(thread)
            return thread

        return wrapper

    monkeypatch.setattr(
        simulator_tab,
        "create_scenario_thread",
        tracking(simulator_tab.create_scenario_thread),
    )
    monkeypatch.setattr(
        main_window,
        "create_worker_thread",
        tracking(main_window.create_worker_thread),
    )
    yield
    app = QApplication.instance()
    for thread in started:
        # The worker's finished -> thread.quit hop is queued to this thread, so
        # keep pumping events while waiting.
        while thread.isRunning():
            if app is not None:
                app.processEvents()
            thread.wait(50)
    if app is not None:
        app.processEvents()


@pytest.fixture(autouse=True)
def isolated_progress(tmp_path, monkeypatch) -> None:
    """Point the default campaign-progress path at a per-test temporary file.

    Autouse and unconditional: any test that builds a ``SimulatorTab`` without
    injecting its own store gets a throwaway file rather than the real one, so
    the suite can never read or write the progress of whoever is running it.
    """
    monkeypatch.setattr(
        progress_module,
        "default_progress_path",
        lambda: tmp_path / "campaign.json",
    )


def pytest_sessionfinish(session, exitstatus) -> None:
    """Destroy leftover Qt widgets before the interpreter starts shutting down.

    Widgets that tests left alive would otherwise be freed during Python's
    final GC, after PySide6 has partly torn itself down, and that crashes the
    process (segfault / bool_dealloc abort) after every test has passed.
    """
    import gc

    from PySide6.QtCore import QCoreApplication, QEvent

    app = QApplication.instance()
    if app is None:
        return
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    gc.collect()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
