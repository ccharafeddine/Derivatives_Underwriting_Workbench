"""Smoke test: the package imports and exposes a version."""

from __future__ import annotations


def test_import_duw() -> None:
    import duw

    assert duw.__version__
