"""App entry-point tests: the headless self-test used to verify frozen builds."""

from __future__ import annotations

from duw import __version__
from duw.app import main, selftest


def test_version_is_set() -> None:
    assert __version__.count(".") == 2


def test_selftest_runs_headless() -> None:
    # Exercises the pipeline plus the plotly/reportlab report paths and returns 0;
    # this is what `DerivativesUnderwritingWorkbench --selftest` runs in a frozen
    # bundle to prove every dependency is present.
    assert selftest() == 0


def test_main_dispatches_selftest() -> None:
    # `--selftest` must not construct a QApplication (so it needs no display).
    assert main(["duw", "--selftest"]) == 0
