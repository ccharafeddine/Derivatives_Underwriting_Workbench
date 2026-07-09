"""A global on/off switch for the app's learning tooltips.

Tooltips are set on widgets unconditionally (see :mod:`duw.ui.help`); whether
they actually appear is decided here by a single application-wide event filter.
When learning tooltips are turned off in the Settings menu, the filter swallows
every ``QEvent.ToolTip`` before Qt shows it, so the whole app goes quiet without
having to clear and restore every widget's tooltip text.

This keeps the toggle O(1): flip one boolean instead of walking the widget tree.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QToolTip,
    QWidget,
)


class TooltipGate(QObject):
    """An application event filter that suppresses tooltips when disabled."""

    def __init__(self, enabled: bool = True) -> None:
        super().__init__()
        self.enabled = enabled

    def set_enabled(self, enabled: bool) -> None:
        """Turn tooltips on or off app-wide."""
        self.enabled = enabled

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt
        if not self.enabled and event.type() == QEvent.Type.ToolTip:
            return True  # consume the event so no tooltip is shown
        return super().eventFilter(obj, event)


def install_tooltip_gate(app: QApplication, enabled: bool) -> TooltipGate:
    """Create a :class:`TooltipGate`, install it on ``app``, and return it."""
    gate = TooltipGate(enabled)
    app.installEventFilter(gate)
    return gate


class HelpBadge(QLabel):
    """A small "?" icon that reveals a field's help on hover or click.

    Hovering shows the help as a normal tooltip (so it obeys the app-wide
    on/off gate); clicking shows it immediately, with no hover delay. Styled via
    the ``helpBadge`` object name in the theme style sheet.
    """

    def __init__(self, help_text: str) -> None:
        super().__init__("?")
        self._help = help_text
        self.setObjectName("helpBadge")
        self.setToolTip(help_text)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(16, 16)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt
        QToolTip.showText(event.globalPosition().toPoint(), self._help, self)
        super().mousePressEvent(event)


def add_help_badges(root: QWidget) -> None:
    """Place a "?" :class:`HelpBadge` beside every helped form field under ``root``.

    For each form row whose field carries a tooltip, the row's label is wrapped
    as ``[label] [?]`` so the learner has a visible, clickable help affordance
    next to the control. Rows without a tooltip, or already badged, are skipped.
    """
    for form in root.findChildren(QFormLayout):
        for row in range(form.rowCount()):
            field_item = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
            label_item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
            if field_item is None or label_item is None:
                continue
            field = field_item.widget()
            label = label_item.widget()
            if field is None or label is None:
                continue
            tip = field.toolTip()
            if not tip or label.property("_has_help_badge"):
                continue
            container = QWidget()
            box = QHBoxLayout(container)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(4)
            box.addWidget(label)  # reparents the label into the container
            box.addWidget(HelpBadge(tip))
            box.addStretch(1)
            label.setProperty("_has_help_badge", True)
            form.setWidget(row, QFormLayout.ItemRole.LabelRole, container)


def set_help_badges_visible(root: QWidget, visible: bool) -> None:
    """Show or hide every :class:`HelpBadge` under ``root`` (tracks the toggle)."""
    for badge in root.findChildren(HelpBadge):
        badge.setVisible(visible)


def mirror_form_label_tooltips(root: QWidget) -> None:
    """Copy each form field's tooltip onto its row label, for every form under ``root``.

    Tooltips are set on the input widgets, but a learner naturally hovers the
    label beside them ("Notional", "Threshold", …). QFormLayout keeps the label
    and field as separate widgets, so this walks every form and gives each label
    its field's tooltip — the help then shows whether you hover the label or the
    box. Labels that already have their own tooltip are left untouched.
    """
    for form in root.findChildren(QFormLayout):
        for row in range(form.rowCount()):
            field_item = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
            label_item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
            if field_item is None or label_item is None:
                continue
            field = field_item.widget()
            label = label_item.widget()
            if field is None or label is None or label.toolTip():
                continue
            tip = field.toolTip()
            if tip:
                label.setToolTip(tip)
