"""Settings, theme, and About tests (Session 12)."""

from __future__ import annotations

from duw.config import (
    KEY_LGD,
    KEY_MC_PATHS,
    KEY_MC_SEED,
    KEY_UPDATE_CHECK,
    AppSettings,
)
from duw.ui.dialogs import SettingsDialog, about_text
from duw.ui.main_window import MainWindow
from duw.ui.theme import THEMES, apply_theme, stylesheet


# --------------------------------------------------------------------------- #
# AppSettings (isolated ini backing)
# --------------------------------------------------------------------------- #
def test_settings_defaults_and_typed_getters(tmp_path) -> None:
    settings = AppSettings(ini_path=str(tmp_path / "s.ini"))
    # Defaults come from config.DEFAULTS when unset.
    assert settings.get_int(KEY_MC_PATHS) == 2000
    assert settings.get_float(KEY_LGD) == 0.6
    settings.set(KEY_MC_PATHS, 500)
    settings.sync()
    # Re-read from a fresh handle over the same file coerces to int.
    reopened = AppSettings(ini_path=str(tmp_path / "s.ini"))
    assert reopened.get_int(KEY_MC_PATHS) == 500


# --------------------------------------------------------------------------- #
# Theme
# --------------------------------------------------------------------------- #
def test_theme_stylesheets_nonempty() -> None:
    for theme in THEMES:
        assert "QWidget" in stylesheet(theme)


def test_apply_theme_sets_stylesheet(qapp) -> None:
    apply_theme(qapp, "dark")
    assert qapp.styleSheet()
    apply_theme(qapp, "light")
    assert "QTabBar" in qapp.styleSheet()


# --------------------------------------------------------------------------- #
# About
# --------------------------------------------------------------------------- #
def test_about_text_carries_disclaimer() -> None:
    text = about_text()
    assert "educational" in text.lower()
    assert "not affiliated" in text.lower()


# --------------------------------------------------------------------------- #
# Settings dialog and its effect on the run config
# --------------------------------------------------------------------------- #
def test_settings_dialog_writes_values(qapp, tmp_path) -> None:
    settings = AppSettings(ini_path=str(tmp_path / "s.ini"))
    dialog = SettingsDialog(settings)
    dialog.paths.setValue(750)
    dialog.seed.setValue(99)
    dialog.lgd.setValue(45.0)
    dialog._on_accept()
    assert settings.get_int(KEY_MC_PATHS) == 750
    assert settings.get_int(KEY_MC_SEED) == 99
    assert settings.get_float(KEY_LGD) == 0.45


def test_main_window_run_config_reads_settings(qapp, tmp_path) -> None:
    window = MainWindow(store=None)
    window.settings = AppSettings(ini_path=str(tmp_path / "s.ini"))
    window.settings.set(KEY_MC_PATHS, 321)
    window.settings.set(KEY_MC_SEED, 7)
    config = window._run_config()
    assert config.n_paths == 321
    assert config.seed == 7


def test_main_window_has_theme_and_help_menus(qapp) -> None:
    window = MainWindow()
    menu_titles = [action.text() for action in window.menuBar().actions()]
    assert "&Help" in menu_titles
    assert "&View" in menu_titles
    # Theme actions exist and one is checked.
    assert any(a.isChecked() for a in window._theme_group.actions())


def test_main_window_set_theme_persists(qapp, tmp_path) -> None:
    window = MainWindow()
    window.settings = AppSettings(ini_path=str(tmp_path / "s.ini"))
    window._set_theme("light")
    assert window.settings.get_str("ui/theme") == "light"


# --------------------------------------------------------------------------- #
# Update-check preference
# --------------------------------------------------------------------------- #
def test_get_bool_coerces_stored_text(tmp_path) -> None:
    settings = AppSettings(ini_path=str(tmp_path / "s.ini"))
    assert settings.get_bool(KEY_UPDATE_CHECK) is False  # default off
    settings.set(KEY_UPDATE_CHECK, True)
    settings.sync()
    reopened = AppSettings(ini_path=str(tmp_path / "s.ini"))
    assert reopened.get_bool(KEY_UPDATE_CHECK) is True


def test_settings_dialog_persists_update_preference(qapp, tmp_path) -> None:
    settings = AppSettings(ini_path=str(tmp_path / "s.ini"))
    dialog = SettingsDialog(settings)
    assert dialog.check_on_startup.isChecked() is False
    dialog.check_on_startup.setChecked(True)
    dialog._on_accept()
    assert settings.get_bool(KEY_UPDATE_CHECK) is True


def test_settings_dialog_update_result_renders(qapp, tmp_path) -> None:
    from duw.updates import UpdateInfo

    settings = AppSettings(ini_path=str(tmp_path / "s.ini"))
    dialog = SettingsDialog(settings)
    # Simulate the async result arriving on the UI thread.
    dialog._on_update_result(
        UpdateInfo(
            current="0.1.0",
            latest="0.9.0",
            url="https://example.com/r",
            available=True,
            error=False,
            message="Update available: 0.9.0.",
        )
    )
    assert "0.9.0" in dialog.update_status.text()
    # isHidden() reflects the explicit flag even when the dialog isn't shown.
    assert not dialog.open_releases_btn.isHidden()
    assert dialog._latest_url == "https://example.com/r"
