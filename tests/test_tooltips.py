"""Learning tooltips: the help registry, the on/off gate, and wiring.

The tooltips are set on widgets unconditionally; a single application event
filter decides whether they show. These check the help text covers the workflow,
the gate suppresses only tooltip events when off, and the main window wires the
tab tooltips and the Settings-menu toggle.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject

from duw.config import KEY_TOOLTIPS, AppSettings
from duw.ui.help import CONTROL_HELP, TAB_HELP, control_help, tab_help
from duw.ui.main_window import TAB_NAMES, MainWindow
from duw.ui.tooltips import TooltipGate


# --------------------------------------------------------------------------- #
# Help registry
# --------------------------------------------------------------------------- #
def test_every_workflow_tab_has_help() -> None:
    for name in TAB_NAMES:
        assert tab_help(name), name
        assert len(TAB_HELP[name]) > 30  # a real sentence, not a stub


def test_control_help_known_and_unknown() -> None:
    for slug in ("notional", "csa_threshold", "wwr", "sim_action", "limit"):
        assert control_help(slug), slug
    assert control_help("does_not_exist") == ""
    # Every registered control help is a non-trivial explanation.
    assert all(len(v) > 20 for v in CONTROL_HELP.values())


# --------------------------------------------------------------------------- #
# Tooltip gate
# --------------------------------------------------------------------------- #
def test_gate_suppresses_only_tooltips_when_disabled() -> None:
    gate = TooltipGate(enabled=True)
    obj = QObject()
    tip = QEvent(QEvent.Type.ToolTip)
    # Enabled: the gate lets the tooltip through (does not consume it).
    assert gate.eventFilter(obj, tip) is False
    # Disabled: the tooltip event is consumed...
    gate.set_enabled(False)
    assert gate.eventFilter(obj, QEvent(QEvent.Type.ToolTip)) is True
    # ...but unrelated events are never touched.
    assert gate.eventFilter(obj, QEvent(QEvent.Type.MouseMove)) is False


def test_tooltips_default_on(tmp_path) -> None:
    settings = AppSettings(ini_path=str(tmp_path / "s.ini"))
    assert settings.get_bool(KEY_TOOLTIPS) is True


# --------------------------------------------------------------------------- #
# Main-window wiring
# --------------------------------------------------------------------------- #
def test_main_window_sets_tab_tooltips(qapp) -> None:
    window = MainWindow()
    for i in range(window.tabs.count()):
        assert window.tabs.tabToolTip(i), window.tabs.tabText(i)


def test_form_labels_mirror_field_tooltips(qapp) -> None:
    from PySide6.QtWidgets import QLabel

    window = MainWindow()
    ct = window.collateral_tab
    tip = ct.threshold.toolTip()
    assert tip
    # Hovering the "Threshold" label shows the field's help (the label carries the
    # same tooltip, even though it is now wrapped alongside its "?" badge).
    threshold_labels = [
        label for label in ct.findChildren(QLabel) if label.text() == "Threshold"
    ]
    assert threshold_labels, "Threshold label not found"
    assert any(label.toolTip() == tip for label in threshold_labels)


def test_toggle_action_flips_the_gate(qapp) -> None:
    window = MainWindow()
    assert window.tooltips_action.isChecked() is True
    assert window._tooltip_gate is not None and window._tooltip_gate.enabled is True
    # Turning the menu item off disables tooltips app-wide via the gate.
    window.tooltips_action.setChecked(False)
    assert window._tooltip_gate.enabled is False
    window.tooltips_action.setChecked(True)
    assert window._tooltip_gate.enabled is True


def test_help_badges_added_and_track_the_toggle(qapp) -> None:
    from duw.ui.tooltips import HelpBadge

    window = MainWindow()
    badges = window.findChildren(HelpBadge)
    assert badges, "expected '?' help badges next to helped fields"
    # Each badge carries a real help string and starts visible (tooltips default on).
    assert all(b.toolTip() for b in badges)
    assert not any(b.isHidden() for b in badges)
    # Turning learning tooltips off hides every badge; on shows them again.
    window.tooltips_action.setChecked(False)
    assert all(b.isHidden() for b in badges)
    window.tooltips_action.setChecked(True)
    assert not any(b.isHidden() for b in badges)
