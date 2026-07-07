"""Background worker.

A QThread worker wrapping the orchestrator, emitting progress and
finished/error signals so the UI never blocks. This is the only pipeline module
that imports Qt."""

from __future__ import annotations

# TODO: implement in a later build session (see BUILD_PLAN.md).
