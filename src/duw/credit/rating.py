"""Rating and PD term structure.

Maps a PD to an internal grade via a lookup table and builds a PD term structure
from CDS if present, else scaled from Merton/rating. No Qt."""

from __future__ import annotations

# TODO: implement in a later build session (see BUILD_PLAN.md).
