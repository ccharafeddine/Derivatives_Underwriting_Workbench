"""Persistence for campaign progress.

A JSON-file-backed store for a :class:`~duw.scenario.campaign.CampaignProgress`,
mirroring :class:`~duw.store.deals.DealStore`: same home-directory location,
same atomic write-to-temp-then-replace, same tolerance of a missing file.

Progress is deliberately kept here rather than in ``QSettings``: it is a
structured record the learner may reasonably want to inspect, back up, or hand
to an instructor, and it sits alongside their saved deals in ``~/.duw/``.

Reads never raise on a damaged file — a learner losing their place is a bad
outcome, but an app that will not open is worse, so a corrupt or unreadable
store degrades to empty progress. No Qt imports.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from duw.scenario.campaign import CampaignProgress


def default_progress_path() -> Path:
    """Default on-disk location of the campaign progress file."""
    return Path.home() / ".duw" / "campaign.json"


class ProgressStore:
    """JSON-file-backed store for a single :class:`CampaignProgress`."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_progress_path()

    def load(self) -> CampaignProgress:
        """Read the saved progress, or empty progress if there is none.

        A missing, empty, malformed, or unreadable file all yield empty progress
        rather than an error: the campaign must always be playable.
        """
        try:
            if not self.path.exists():
                return CampaignProgress()
            raw = self.path.read_text(encoding="utf-8").strip()
            if not raw:
                return CampaignProgress()
            data: Any = json.loads(raw)
            if not isinstance(data, dict):
                return CampaignProgress()
            return CampaignProgress.from_dict(data)
        except (OSError, ValueError):
            return CampaignProgress()

    def save(self, progress: CampaignProgress) -> None:
        """Write ``progress`` atomically, creating the directory if needed."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(progress.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def clear(self) -> None:
        """Delete the stored progress file if it exists."""
        self.path.unlink(missing_ok=True)
