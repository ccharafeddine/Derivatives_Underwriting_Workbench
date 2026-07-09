"""Settings and About dialogs.

``SettingsDialog`` edits the Monte Carlo and credit defaults and the update-check
preference, backed by :class:`AppSettings`. ``show_about`` shows the version and
the full disclaimer, sourced from the single canonical :data:`DISCLAIMER`
constant so the app and the generated memos never drift.
"""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from duw import __version__
from duw.config import (
    KEY_FUNDING_BPS,
    KEY_LGD,
    KEY_MC_PATHS,
    KEY_MC_SEED,
    KEY_MC_STEPS,
    KEY_TOOLTIPS,
    KEY_UPDATE_CHECK,
    KEY_WWR,
    AppSettings,
)
from duw.glossary import GLOSSARY
from duw.reports.interpreter import DISCLAIMER
from duw.ui.help import control_help
from duw.ui.tooltips import (
    add_help_badges,
    mirror_form_label_tooltips,
    set_help_badges_visible,
)
from duw.ui.update_check import check_async
from duw.updates import UpdateInfo


class SettingsDialog(QDialog):
    """Edit Monte Carlo defaults, LGD, and the update-check preference."""

    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self._settings = settings
        self._update_signals = None
        self._latest_url = ""

        self.paths = QSpinBox()
        self.paths.setRange(100, 200_000)
        self.paths.setSingleStep(100)
        self.paths.setValue(settings.get_int(KEY_MC_PATHS))

        self.steps = QSpinBox()
        self.steps.setRange(2, 52)
        self.steps.setValue(settings.get_int(KEY_MC_STEPS))

        self.seed = QSpinBox()
        self.seed.setRange(0, 2_147_483_647)
        self.seed.setValue(settings.get_int(KEY_MC_SEED))

        self.lgd = QDoubleSpinBox()
        self.lgd.setRange(1.0, 100.0)
        self.lgd.setDecimals(1)
        self.lgd.setSuffix(" %")
        self.lgd.setValue(settings.get_float(KEY_LGD) * 100.0)

        self.funding = QDoubleSpinBox()
        self.funding.setRange(0.0, 1000.0)
        self.funding.setDecimals(0)
        self.funding.setSuffix(" bps")
        self.funding.setToolTip("Funding spread used for FVA (0 = no FVA).")
        self.funding.setValue(settings.get_float(KEY_FUNDING_BPS))

        self.wwr = QDoubleSpinBox()
        self.wwr.setRange(-1.0, 1.0)
        self.wwr.setDecimals(2)
        self.wwr.setSingleStep(0.1)
        self.wwr.setToolTip(
            "Wrong-way risk: exposure-credit correlation (0 = independence, "
            "positive raises CVA)."
        )
        self.wwr.setValue(settings.get_float(KEY_WWR))

        self.paths.setToolTip(control_help("mc_paths"))
        self.steps.setToolTip(control_help("mc_steps"))
        self.seed.setToolTip(control_help("mc_seed"))
        self.lgd.setToolTip(control_help("lgd"))
        self.funding.setToolTip(control_help("funding_bps"))
        self.wwr.setToolTip(control_help("wwr"))

        form = QFormLayout()
        form.addRow("Monte Carlo paths", self.paths)
        form.addRow("Time-grid steps", self.steps)
        form.addRow("Random seed", self.seed)
        form.addRow("Default LGD", self.lgd)
        form.addRow("Funding spread (FVA)", self.funding)
        form.addRow("Wrong-way corr.", self.wwr)
        form.addRow("Confidence levels", QLabel("95% and 99% (fixed)"))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._build_updates_box())
        layout.addWidget(buttons)

        # Let the field tooltips also show when hovering their labels, and add a
        # "?" help icon next to each, in step with the app-wide tooltips toggle.
        mirror_form_label_tooltips(self)
        add_help_badges(self)
        set_help_badges_visible(self, settings.get_bool(KEY_TOOLTIPS))

    def _build_updates_box(self) -> QGroupBox:
        box = QGroupBox("Updates")
        layout = QVBoxLayout(box)
        self.check_on_startup = QCheckBox("Check for updates on startup")
        self.check_on_startup.setChecked(self._settings.get_bool(KEY_UPDATE_CHECK))
        layout.addWidget(self.check_on_startup)

        row = QHBoxLayout()
        self.check_now_btn = QPushButton("Check for updates now")
        self.check_now_btn.clicked.connect(self._on_check_now)
        self.open_releases_btn = QPushButton("View release")
        self.open_releases_btn.setVisible(False)
        self.open_releases_btn.clicked.connect(self._open_releases)
        row.addWidget(self.check_now_btn)
        row.addWidget(self.open_releases_btn)
        row.addStretch(1)
        layout.addLayout(row)

        self.update_status = QLabel(f"Current version: {__version__}")
        self.update_status.setObjectName("update_status")
        self.update_status.setWordWrap(True)
        layout.addWidget(self.update_status)
        return box

    # -- updates ----------------------------------------------------------- #
    def _on_check_now(self) -> None:
        self.check_now_btn.setEnabled(False)
        self.open_releases_btn.setVisible(False)
        self.update_status.setText("Checking for updates…")
        self._update_signals = check_async(self._on_update_result)

    def _on_update_result(self, info: UpdateInfo) -> None:
        self.check_now_btn.setEnabled(True)
        self.update_status.setText(info.message)
        self._latest_url = info.url
        self.open_releases_btn.setVisible(info.available)

    def _open_releases(self) -> None:
        if self._latest_url:
            QDesktopServices.openUrl(QUrl(self._latest_url))

    # -- persistence ------------------------------------------------------- #
    def _on_accept(self) -> None:
        self._settings.set(KEY_MC_PATHS, self.paths.value())
        self._settings.set(KEY_MC_STEPS, self.steps.value())
        self._settings.set(KEY_MC_SEED, self.seed.value())
        self._settings.set(KEY_LGD, self.lgd.value() / 100.0)
        self._settings.set(KEY_FUNDING_BPS, self.funding.value())
        self._settings.set(KEY_WWR, self.wwr.value())
        self._settings.set(KEY_UPDATE_CHECK, self.check_on_startup.isChecked())
        self._settings.sync()
        self.accept()


def about_text() -> str:
    """The About dialog body: framing, version, and the full disclaimer."""
    return (
        f"<b>Derivatives Underwriting Workbench</b> v{__version__}<br><br>"
        "An educational portfolio project that reconstructs the counterparty-"
        "credit underwriting workflow for OTC derivatives. It runs on synthetic "
        "and public data only.<br><br>"
        f"<i>{DISCLAIMER}</i>"
    )


def show_about(parent: QWidget | None = None) -> None:
    """Show the About / disclaimer dialog."""
    QMessageBox.about(parent, "About Derivatives Underwriting Workbench", about_text())


def build_glossary_dialog(parent: QWidget | None = None) -> QDialog:
    """Build (without showing) a dialog listing the glossary terms."""
    dialog = QDialog(parent)
    dialog.setWindowTitle("Glossary")
    dialog.resize(660, 500)

    table = QTableWidget(len(GLOSSARY), 2, dialog)
    table.setHorizontalHeaderLabels(["Term", "Definition"])
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    table.setWordWrap(True)
    header = table.horizontalHeader()
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    for row, (term, definition) in enumerate(sorted(GLOSSARY.items())):
        table.setItem(row, 0, QTableWidgetItem(term))
        table.setItem(row, 1, QTableWidgetItem(definition))
    table.resizeRowsToContents()

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dialog.reject)
    buttons.accepted.connect(dialog.accept)

    layout = QVBoxLayout(dialog)
    layout.addWidget(table)
    layout.addWidget(buttons)
    return dialog


def show_glossary(parent: QWidget | None = None) -> None:
    """Show the glossary dialog."""
    build_glossary_dialog(parent).exec()
