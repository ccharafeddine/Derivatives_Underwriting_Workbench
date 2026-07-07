"""Risk-factor simulators.

Seeded simulators: Hull-White one-factor short rate (Vasicek fallback), GBM FX
spot, and a mean-reverting credit spread. Explicit rng/seed; no global random
state. No Qt."""

from __future__ import annotations

# TODO: implement in a later build session (see BUILD_PLAN.md).
