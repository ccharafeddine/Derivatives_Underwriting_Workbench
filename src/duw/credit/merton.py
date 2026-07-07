"""Merton / KMV distance-to-default.

Solves for asset value and vol from equity value, equity vol, and debt, then
computes distance-to-default and PD = N(-DtD). No Qt."""

from __future__ import annotations

# TODO: implement in a later build session (see BUILD_PLAN.md).
