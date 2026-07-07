"""Trade instruments and netting sets.

Defines the Trade base plus IRS, FXForward, and CDS dataclasses
and the NettingSet that groups a counterparty's trades under one ISDA
master. Frozen dataclasses; no Qt imports."""

from __future__ import annotations

# TODO: implement in a later build session (see BUILD_PLAN.md).
