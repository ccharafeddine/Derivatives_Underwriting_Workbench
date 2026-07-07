"""Pipeline orchestrator.

Runs the sequential analysis steps in order, threading a single
AnalysisResults through, given a run config with the Monte Carlo seed.
Qt-free (Qt lives in worker.py)."""

from __future__ import annotations

# TODO: implement in a later build session (see BUILD_PLAN.md).
