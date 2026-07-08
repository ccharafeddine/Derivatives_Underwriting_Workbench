"""Counterparty input tab.

Select one of the synthetic seed counterparties or enter a custom one, showing
the balance-sheet financials that feed the Merton and Altman models. A
form/summary :class:`QSplitter` previews the built counterparty and a couple of
headline ratios. Qt lives here; no analytics — the tab only captures and
validates input, then pushes the :class:`~duw.domain.counterparty.Counterparty`
to the shared :class:`~duw.ui.app_state.AppState`.

Financial amounts are entered in the same consistent units as the bundled seed
data (millions of the reporting currency).
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from duw.domain.counterparty import Counterparty, Financials
from duw.ui.app_state import AppState
from duw.ui.financials_fetch import fetch_async

_CUSTOM = "Custom…"
_CURRENCIES = ("USD", "EUR")

# The financial fields, in display order: (attribute, label, default).
_FIN_FIELDS: tuple[tuple[str, str, float], ...] = (
    ("total_assets", "Total assets", 5000.0),
    ("total_liabilities", "Total liabilities", 3000.0),
    ("current_assets", "Current assets", 2000.0),
    ("current_liabilities", "Current liabilities", 1200.0),
    ("retained_earnings", "Retained earnings", 800.0),
    ("ebit", "EBIT", 600.0),
    ("sales", "Sales", 4000.0),
    ("market_equity", "Market equity", 2500.0),
)


def _amount_spin(default: float) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(-1e9, 1e9)
    spin.setDecimals(1)
    spin.setGroupSeparatorShown(True)
    spin.setValue(default)
    return spin


class CounterpartyTab(QWidget):
    """Counterparty selector/entry producing a validated ``Counterparty``."""

    def __init__(self, app_state: AppState | None = None) -> None:
        super().__init__()
        self._app_state = app_state
        self._seeds = list(app_state.counterparties) if app_state else []
        self._fin_spins: dict[str, QDoubleSpinBox] = {}
        self._fetch_signals = None
        self._build_ui()
        self._populate_from_selection()
        self._refresh()

    # -- construction ------------------------------------------------------ #
    def _build_ui(self) -> None:
        splitter = QSplitter()

        form_panel = QWidget()
        form = QFormLayout(form_panel)

        self.selector = QComboBox()
        for cp in self._seeds:
            self.selector.addItem(f"{cp.counterparty_id} — {cp.name}", cp)
        self.selector.addItem(_CUSTOM, None)
        form.addRow("Counterparty", self.selector)

        self.name = QLineEdit()
        form.addRow("Name", self.name)
        self.sector = QLineEdit()
        form.addRow("Sector", self.sector)
        self.ticker = QLineEdit()
        self.ticker.setPlaceholderText("optional public ticker")
        self.fetch_btn = QPushButton("Fetch")
        self.fetch_btn.setToolTip(
            "Pull financials for this ticker via yfinance (offline-safe; "
            "keeps current values on failure)."
        )
        self.fetch_btn.clicked.connect(self._on_fetch)
        ticker_row = QHBoxLayout()
        ticker_row.addWidget(self.ticker)
        ticker_row.addWidget(self.fetch_btn)
        ticker_widget = QWidget()
        ticker_widget.setLayout(ticker_row)
        form.addRow("Ticker", ticker_widget)
        self.fetch_status = QLabel("")
        self.fetch_status.setObjectName("fetch_status")
        self.fetch_status.setWordWrap(True)
        form.addRow("", self.fetch_status)
        self.cds_issuer = QLineEdit()
        self.cds_issuer.setPlaceholderText("optional CDS issuer key")
        form.addRow("CDS issuer", self.cds_issuer)
        self.rating = QLineEdit()
        self.rating.setPlaceholderText("optional seeded rating")
        form.addRow("Internal rating", self.rating)

        fin_box = QGroupBox("Financials (millions)")
        fin_form = QFormLayout(fin_box)
        for attr, label, default in _FIN_FIELDS:
            spin = _amount_spin(default)
            self._fin_spins[attr] = spin
            fin_form.addRow(label, spin)
        self.equity_vol = QDoubleSpinBox()
        self.equity_vol.setRange(1.0, 200.0)
        self.equity_vol.setDecimals(1)
        self.equity_vol.setSuffix(" %")
        self.equity_vol.setValue(30.0)
        fin_form.addRow("Equity volatility", self.equity_vol)
        self.fin_currency = QComboBox()
        self.fin_currency.addItems(_CURRENCIES)
        fin_form.addRow("Currency", self.fin_currency)
        form.addRow(fin_box)

        splitter.addWidget(form_panel)

        summary_panel = QWidget()
        summary_layout = QVBoxLayout(summary_panel)
        summary_layout.addWidget(QLabel("<b>Counterparty summary</b>"))
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setObjectName("counterparty_summary")
        summary_layout.addWidget(self.summary)
        summary_layout.addStretch(1)
        self.status = QLabel()
        self.status.setObjectName("counterparty_status")
        self.status.setWordWrap(True)
        summary_layout.addWidget(self.status)
        splitter.addWidget(summary_panel)
        splitter.setSizes([560, 360])

        outer = QHBoxLayout(self)
        outer.addWidget(splitter)

        self.selector.currentIndexChanged.connect(self._on_selection_changed)
        for widget in (
            self.name,
            self.sector,
            self.ticker,
            self.cds_issuer,
            self.rating,
        ):
            widget.textChanged.connect(self._refresh)
        for spin in self._fin_spins.values():
            spin.valueChanged.connect(self._refresh)
        self.equity_vol.valueChanged.connect(self._refresh)
        self.fin_currency.currentIndexChanged.connect(self._refresh)

    # -- selection --------------------------------------------------------- #
    def select_seed(self, counterparty_id: str) -> bool:
        """Select the seed counterparty with ``counterparty_id`` if present."""
        for i in range(self.selector.count()):
            cp = self.selector.itemData(i)
            if cp is not None and cp.counterparty_id == counterparty_id:
                self.selector.setCurrentIndex(i)
                return True
        return False

    def _on_selection_changed(self) -> None:
        self._populate_from_selection()
        self._refresh()

    def _populate_from_selection(self) -> None:
        cp = self.selector.currentData()
        if cp is None:
            return  # custom: leave the current field values in place
        self.name.setText(cp.name)
        self.sector.setText(cp.sector)
        self.ticker.setText(cp.ticker or "")
        self.cds_issuer.setText(cp.cds_issuer or "")
        self.rating.setText(cp.internal_rating or "")
        if cp.financials is not None:
            self._set_financials(cp.financials)

    def _set_financials(self, fin: Financials) -> None:
        for attr, spin in self._fin_spins.items():
            spin.setValue(getattr(fin, attr))
        self.equity_vol.setValue(fin.equity_volatility * 100.0)
        self.fin_currency.setCurrentText(fin.currency)

    # -- live financials fetch --------------------------------------------- #
    def _on_fetch(self) -> None:
        ticker = self.ticker.text().strip()
        if not ticker:
            self.fetch_status.setText("Enter a ticker to fetch.")
            return
        self.fetch_btn.setEnabled(False)
        self.fetch_status.setText(f"Fetching {ticker}…")
        self._fetch_signals = fetch_async(
            ticker,
            self.equity_vol.value() / 100.0,
            self.fin_currency.currentText(),
            self._on_fetched,
        )

    def _on_fetched(self, fin: Financials | None) -> None:
        self.fetch_btn.setEnabled(True)
        ticker = self.ticker.text().strip()
        if fin is not None:
            self._set_financials(fin)
            self.fetch_status.setText(
                f"<span style='color:#2e7d32'>Loaded financials for {ticker}.</span>"
            )
        else:
            self.fetch_status.setText(
                "<span style='color:#c62828'>Could not fetch — kept current "
                "values (offline or unknown ticker).</span>"
            )
        self._refresh()

    # -- state ------------------------------------------------------------- #
    def build_counterparty(self) -> Counterparty | None:
        """Return the currently specified counterparty, or ``None`` if invalid."""
        cp, _error = self._build()
        return cp

    def is_valid(self) -> bool:
        return self.build_counterparty() is not None

    def _build(self) -> tuple[Counterparty | None, str]:
        name = self.name.text().strip()
        if not name:
            return None, "Name is required."
        financials = Financials(
            total_assets=self._fin_spins["total_assets"].value(),
            total_liabilities=self._fin_spins["total_liabilities"].value(),
            current_assets=self._fin_spins["current_assets"].value(),
            current_liabilities=self._fin_spins["current_liabilities"].value(),
            retained_earnings=self._fin_spins["retained_earnings"].value(),
            ebit=self._fin_spins["ebit"].value(),
            sales=self._fin_spins["sales"].value(),
            market_equity=self._fin_spins["market_equity"].value(),
            equity_volatility=self.equity_vol.value() / 100.0,
            currency=self.fin_currency.currentText(),
        )
        if financials.total_assets <= 0.0 or financials.total_liabilities <= 0.0:
            return None, "Total assets and liabilities must be positive."

        seed = self.selector.currentData()
        counterparty_id = seed.counterparty_id if seed is not None else "CP-CUSTOM"
        return (
            Counterparty(
                counterparty_id=counterparty_id,
                name=name,
                sector=self.sector.text().strip() or "Unspecified",
                ticker=self.ticker.text().strip() or None,
                financials=financials,
                cds_issuer=self.cds_issuer.text().strip() or None,
                internal_rating=self.rating.text().strip() or None,
            ),
            "",
        )

    def _refresh(self) -> None:
        cp, error = self._build()
        if cp is not None:
            self.summary.setText(self._describe(cp))
            self.status.setText(
                "<span style='color:#2e7d32'>Valid counterparty.</span>"
            )
        else:
            self.summary.setText("—")
            self.status.setText(f"<span style='color:#c62828'>{error}</span>")
        if self._app_state is not None:
            self._app_state.set_counterparty(cp)

    @staticmethod
    def _describe(cp: Counterparty) -> str:
        fin = cp.financials
        lines = [
            f"<b>{cp.name}</b> ({cp.counterparty_id})",
            f"Sector: {cp.sector}",
        ]
        if cp.ticker:
            lines.append(f"Ticker: {cp.ticker}")
        if cp.cds_issuer:
            lines.append(f"CDS issuer: {cp.cds_issuer}")
        if fin is not None:
            leverage = fin.total_liabilities / fin.total_assets
            lines.append(
                f"Assets {fin.total_assets:,.0f} / Liabilities "
                f"{fin.total_liabilities:,.0f} ({leverage:.0%} leverage)"
            )
            lines.append(
                f"Working capital {fin.working_capital:,.0f}, "
                f"equity vol {fin.equity_volatility:.0%}"
            )
        return "<br>".join(lines)
