"""Shared pytest fixtures.

Provides a session-scoped ``QApplication`` for Qt widget tests. Qt tests must
run headlessly; set ``QT_QPA_PLATFORM=offscreen`` in the environment when
invoking pytest.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """Return the process-wide QApplication, creating it if needed."""
    return QApplication.instance() or QApplication([])
