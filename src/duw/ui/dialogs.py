"""Settings and About dialogs.

``SettingsDialog`` edits the Monte Carlo and credit defaults backed by
:class:`AppSettings`. ``show_about`` shows the version and the full disclaimer,
sourced from the single canonical :data:`DISCLAIMER` constant so the app and the
generated memos never drift.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from duw import __version__
from duw.config import (
    KEY_LGD,
    KEY_MC_PATHS,
    KEY_MC_SEED,
    KEY_MC_STEPS,
    AppSettings,
)
from duw.reports.interpreter import DISCLAIMER


class SettingsDialog(QDialog):
    """Edit Monte Carlo paths / steps / seed and the default LGD."""

    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self._settings = settings

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

        form = QFormLayout()
        form.addRow("Monte Carlo paths", self.paths)
        form.addRow("Time-grid steps", self.steps)
        form.addRow("Random seed", self.seed)
        form.addRow("Default LGD", self.lgd)
        form.addRow("Confidence levels", QLabel("95% and 99% (fixed)"))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        self._settings.set(KEY_MC_PATHS, self.paths.value())
        self._settings.set(KEY_MC_STEPS, self.steps.value())
        self._settings.set(KEY_MC_SEED, self.seed.value())
        self._settings.set(KEY_LGD, self.lgd.value() / 100.0)
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
