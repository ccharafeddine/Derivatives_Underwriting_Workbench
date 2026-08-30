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
