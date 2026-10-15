"""Application settings.

A thin ``AppSettings`` wrapper over :class:`QSettings`, giving the rest of the
app a small typed surface for reading and writing persisted preferences with
sane defaults. Qt is allowed here (this is one of the few Qt-aware non-UI
modules, alongside ``app.py`` and ``pipeline/worker.py``).

Tests can pass ``ini_path`` to back the settings with an isolated ini file
instead of the platform-native store.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QSettings

ORG_NAME = "DerivativesUnderwritingWorkbench"
APP_NAME = "duw"

# Settings keys and their defaults, so the UI and the run pipeline agree.
KEY_THEME = "ui/theme"
KEY_MC_PATHS = "mc/n_paths"
KEY_MC_STEPS = "mc/n_steps"
KEY_MC_SEED = "mc/seed"
KEY_LGD = "credit/lgd"
KEY_FUNDING_BPS = "credit/funding_spread_bps"
KEY_WWR = "credit/wwr_correlation"
KEY_UPDATE_CHECK = "updates/check_on_startup"
KEY_TOOLTIPS = "ui/learning_tooltips"
# Set once the one-time move to the Graphite redesign has happened, so a user
# who later picks another theme keeps it.
KEY_THEME_MIGRATED = "ui/graphite_migrated"

DEFAULTS: dict[str, Any] = {
    KEY_THEME: "graphite",
    KEY_MC_PATHS: 2000,
    KEY_MC_STEPS: 12,
    KEY_MC_SEED: 12345,
    KEY_LGD: 0.6,
    KEY_FUNDING_BPS: 0.0,
    KEY_WWR: 0.0,
    KEY_UPDATE_CHECK: False,
    KEY_TOOLTIPS: True,
}


class AppSettings:
    """Typed convenience wrapper over :class:`QSettings`.

    Persists preferences to the platform-native store (registry on Windows,
    ``.plist`` on macOS, ini/keyring on Linux) under a stable org/app name so
    settings survive across sessions.
    """

    def __init__(
        self, org: str = ORG_NAME, app: str = APP_NAME, ini_path: str | None = None
    ) -> None:
        if ini_path is not None:
            self._settings = QSettings(ini_path, QSettings.Format.IniFormat)
        else:
            self._settings = QSettings(org, app)

    def get(self, key: str, default: Any = None) -> Any:
        """Return the stored value for ``key`` or ``default`` if unset."""
        fallback = DEFAULTS.get(key, default)
        return self._settings.value(key, fallback)

    def get_int(self, key: str, default: int | None = None) -> int:
        """Return ``key`` coerced to ``int`` (QSettings may store as text)."""
        return int(self.get(key, default))

    def get_float(self, key: str, default: float | None = None) -> float:
        """Return ``key`` coerced to ``float``."""
        return float(self.get(key, default))

    def get_str(self, key: str, default: str | None = None) -> str:
        """Return ``key`` coerced to ``str``."""
        return str(self.get(key, default))

    def get_bool(self, key: str, default: bool | None = None) -> bool:
        """Return ``key`` coerced to ``bool`` (QSettings may store as text)."""
        value = self.get(key, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    def set(self, key: str, value: Any) -> None:
        """Store ``value`` under ``key``."""
        self._settings.setValue(key, value)

    def contains(self, key: str) -> bool:
        """Return whether ``key`` has a stored value."""
        return self._settings.contains(key)

    def remove(self, key: str) -> None:
        """Delete the stored value for ``key`` if present."""
        self._settings.remove(key)

    def migrate_theme(self) -> None:
        """Move a pre-redesign default theme to Graphite, exactly once.

        Earlier versions defaulted to the amber "dark" theme and wrote it back
        on every theme change, so a stored "dark" mostly means "never chose".
        The first launch of the redesign switches it to Graphite; after that
        the stored choice is respected (the old themes stay selectable).
        """
        if self.get_bool(KEY_THEME_MIGRATED, False):
            return
        if self.get_str(KEY_THEME) == "dark":
            self.set(KEY_THEME, "graphite")
        self.set(KEY_THEME_MIGRATED, True)
        self.sync()

    def sync(self) -> None:
        """Flush any pending writes to the backing store."""
        self._settings.sync()
