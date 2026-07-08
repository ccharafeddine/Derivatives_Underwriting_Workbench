"""Update checking against GitHub Releases.

Queries the project's GitHub Releases API for the latest published version and
compares it against the running version. Pure Python (stdlib ``urllib`` only, no
new dependency); the network call is opt-in and off the UI thread, and every
failure degrades gracefully so the offline-first app is never blocked.

The ``fetch`` callable is injectable so the logic can be tested without network.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from duw import __version__

REPO = "ccharafeddine/Derivatives_Underwriting_Workbench"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"


class NoReleasesError(Exception):
    """Raised by the fetcher when the repo has no published releases (404)."""


@dataclass(frozen=True)
class UpdateInfo:
    """Result of an update check."""

    current: str
    latest: str | None
    url: str
    available: bool
    error: bool
    message: str


def parse_version(text: str) -> tuple[int, ...]:
    """Parse a version string like ``v1.2.3`` into ``(1, 2, 3)``."""
    cleaned = text.strip().lstrip("vV")
    parts: list[int] = []
    for chunk in cleaned.split(".")[:3]:
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer(latest: str, current: str) -> bool:
    """Whether ``latest`` is a strictly newer version than ``current``."""
    return parse_version(latest) > parse_version(current)


def _default_fetch(url: str, timeout: float) -> dict:
    import json
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "duw-update-check",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise NoReleasesError() from exc
        raise


def check_for_updates(
    current: str = __version__,
    *,
    timeout: float = 4.0,
    fetch: Callable[[str, float], dict] | None = None,
) -> UpdateInfo:
    """Check GitHub Releases for a newer version than ``current``."""
    fetch = fetch or _default_fetch
    try:
        data = fetch(RELEASES_API, timeout)
    except NoReleasesError:
        return UpdateInfo(
            current=current,
            latest=None,
            url=RELEASES_PAGE,
            available=False,
            error=False,
            message=f"No published releases yet — you're on {current}.",
        )
    except Exception as exc:  # network down, timeout, rate limit, schema drift
        return UpdateInfo(
            current=current,
            latest=None,
            url=RELEASES_PAGE,
            available=False,
            error=True,
            message=f"Could not check for updates: {exc}",
        )

    latest_raw = str(data.get("tag_name") or data.get("name") or "").strip()
    html_url = str(data.get("html_url") or RELEASES_PAGE)
    latest = latest_raw.lstrip("vV")
    if not latest:
        return UpdateInfo(
            current,
            None,
            RELEASES_PAGE,
            False,
            True,
            "Could not determine the latest version.",
        )
    if is_newer(latest, current):
        return UpdateInfo(
            current,
            latest,
            html_url,
            True,
            False,
            f"Update available: {latest} (you have {current}).",
        )
    return UpdateInfo(
        current,
        latest,
        html_url,
        False,
        False,
        f"You're up to date ({current}).",
    )
