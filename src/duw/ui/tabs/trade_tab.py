"""Trade input tab.

A term-sheet form that switches its economic-terms fields by product (interest
rate swap / FX forward / credit default swap), validates the inputs, and builds
a typed :class:`~duw.domain.instruments.Trade`. A form/summary
:class:`QSplitter` shows the built trade and any validation error.

Rates and spreads are entered in intuitive units (percent, basis points) and
converted to decimals for the domain object. Leg day counts use the domain
defaults to keep the form focused on the primary economic terms. Qt lives here.
No analytics: the tab only captures and validates input, then pushes the trade
to the shared :class:`~duw.ui.app_state.AppState`.
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from duw.domain.instruments import (
    CDS,
    IRS,
    CdsDirection,
    Frequency,
    FxDirection,
    FXForward,
    SwapDirection,
    Trade,
)
from duw.ui.app_state import AppState

_CURRENCIES = ("USD", "EUR")
_PRODUCTS = ("Interest Rate Swap", "FX Forward", "Credit Default Swap")


def _money_spin(default: float) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(0.0, 1e12)
    spin.setDecimals(0)
    spin.setGroupSeparatorShown(True)
    spin.setValue(default)
    return spin


def _rate_spin(default: float, suffix: str, decimals: int = 3) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(-100.0, 100.0)
    spin.setDecimals(decimals)
    spin.setSuffix(suffix)
    spin.setValue(default)
    return spin


def _frequency_combo(default: Frequency) -> QComboBox:
    combo = QComboBox()
    for freq in Frequency:
        combo.addItem(freq.name.title(), freq)
    combo.setCurrentIndex(list(Frequency).index(default))
    return combo


class TradeTab(QWidget):
    """Term-sheet form producing a validated :class:`Trade`."""

    def __init__(self, app_state: AppState | None = None) -> None:
        super().__init__()
        self._app_state = app_state
        self._build_ui()
        self._refresh()

    # -- construction ------------------------------------------------------ #
    def _build_ui(self) -> None:
        splitter = QSplitter()

        form_panel = QWidget()
        form = QFormLayout(form_panel)

        self.product = QComboBox()
        self.product.addItems(_PRODUCTS)
        form.addRow("Product", self.product)

        self.trade_id = QLineEdit("TRD-001")
        form.addRow("Trade ID", self.trade_id)

        self.notional = _money_spin(10_000_000.0)
        form.addRow("Notional", self.notional)

        self.currency = QComboBox()
        self.currency.addItems(_CURRENCIES)
        form.addRow("Currency", self.currency)

        self.trade_date = QDateEdit()
        self.trade_date.setCalendarPopup(True)
        self.trade_date.setDisplayFormat("yyyy-MM-dd")
        self.trade_date.setDate(QDate(2025, 6, 30))
        form.addRow("Trade date", self.trade_date)

        self.maturity_date = QDateEdit()
        self.maturity_date.setCalendarPopup(True)
        self.maturity_date.setDisplayFormat("yyyy-MM-dd")
        self.maturity_date.setDate(QDate(2030, 6, 30))
        form.addRow("Maturity date", self.maturity_date)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_irs_page())
        self.stack.addWidget(self._build_fx_page())
        self.stack.addWidget(self._build_cds_page())
        form.addRow(self.stack)

        splitter.addWidget(form_panel)

        summary_panel = QWidget()
        summary_layout = QVBoxLayout(summary_panel)
        summary_layout.addWidget(QLabel("<b>Trade summary</b>"))
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setObjectName("trade_summary")
        summary_layout.addWidget(self.summary)
        summary_layout.addStretch(1)
        self.status = QLabel()
        self.status.setObjectName("trade_status")
        self.status.setWordWrap(True)
        summary_layout.addWidget(self.status)
        splitter.addWidget(summary_panel)
        splitter.setSizes([560, 360])

        outer = QHBoxLayout(self)
        outer.addWidget(splitter)

        # React to any change.
        self.product.currentIndexChanged.connect(self.stack.setCurrentIndex)
        self.product.currentIndexChanged.connect(self._refresh)
        for widget in (self.trade_id,):
            widget.textChanged.connect(self._refresh)
        self.notional.valueChanged.connect(self._refresh)
        self.currency.currentIndexChanged.connect(self._refresh)
        self.trade_date.dateChanged.connect(self._refresh)
        self.maturity_date.dateChanged.connect(self._refresh)

    def _build_irs_page(self) -> QWidget:
        box = QGroupBox("Swap terms")
        form = QFormLayout(box)
        self.irs_fixed_rate = _rate_spin(4.3, " %")
        self.irs_direction = QComboBox()
        self.irs_direction.addItem("Pay fixed", SwapDirection.PAY_FIXED)
        self.irs_direction.addItem("Receive fixed", SwapDirection.RECEIVE_FIXED)
        self.irs_fixed_freq = _frequency_combo(Frequency.ANNUAL)
        self.irs_float_freq = _frequency_combo(Frequency.QUARTERLY)
        self.irs_float_spread = _rate_spin(0.0, " bps", decimals=1)
        self.irs_float_spread.setRange(-1000.0, 1000.0)
        form.addRow("Fixed rate", self.irs_fixed_rate)
        form.addRow("Direction", self.irs_direction)
        form.addRow("Fixed frequency", self.irs_fixed_freq)
        form.addRow("Float frequency", self.irs_float_freq)
        form.addRow("Float spread", self.irs_float_spread)
        for w in (self.irs_fixed_rate, self.irs_float_spread):
            w.valueChanged.connect(self._refresh)
        self.irs_direction.currentIndexChanged.connect(self._refresh)
        self.irs_fixed_freq.currentIndexChanged.connect(self._refresh)
        self.irs_float_freq.currentIndexChanged.connect(self._refresh)
        return box

    def _build_fx_page(self) -> QWidget:
        box = QGroupBox("FX forward terms")
        form = QFormLayout(box)
        self.fx_base = QComboBox()
        self.fx_base.addItems(_CURRENCIES)
        self.fx_base.setCurrentText("EUR")
        self.fx_quote = QComboBox()
        self.fx_quote.addItems(_CURRENCIES)
        self.fx_quote.setCurrentText("USD")
        self.fx_rate = QDoubleSpinBox()
        self.fx_rate.setRange(0.0, 1000.0)
        self.fx_rate.setDecimals(4)
        self.fx_rate.setValue(1.0800)
        self.fx_direction = QComboBox()
        self.fx_direction.addItem("Buy base", FxDirection.BUY_BASE)
        self.fx_direction.addItem("Sell base", FxDirection.SELL_BASE)
        form.addRow("Base currency", self.fx_base)
        form.addRow("Quote currency", self.fx_quote)
        form.addRow("Contract rate", self.fx_rate)
        form.addRow("Direction", self.fx_direction)
        self.fx_base.currentIndexChanged.connect(self._refresh)
        self.fx_quote.currentIndexChanged.connect(self._refresh)
        self.fx_rate.valueChanged.connect(self._refresh)
        self.fx_direction.currentIndexChanged.connect(self._refresh)
        return box

    def _build_cds_page(self) -> QWidget:
        box = QGroupBox("CDS terms")
        form = QFormLayout(box)
        self.cds_reference = QLineEdit("ACME")
        self.cds_direction = QComboBox()
        self.cds_direction.addItem("Buy protection", CdsDirection.BUY_PROTECTION)
        self.cds_direction.addItem("Sell protection", CdsDirection.SELL_PROTECTION)
        self.cds_spread = _rate_spin(100.0, " bps", decimals=1)
        self.cds_spread.setRange(0.0, 10000.0)
        self.cds_premium_freq = _frequency_combo(Frequency.QUARTERLY)
        self.cds_recovery = _rate_spin(40.0, " %", decimals=1)
        self.cds_recovery.setRange(0.0, 99.0)
        form.addRow("Reference entity", self.cds_reference)
        form.addRow("Direction", self.cds_direction)
        form.addRow("Spread", self.cds_spread)
        form.addRow("Premium frequency", self.cds_premium_freq)
        form.addRow("Recovery rate", self.cds_recovery)
        self.cds_reference.textChanged.connect(self._refresh)
        self.cds_direction.currentIndexChanged.connect(self._refresh)
        self.cds_spread.valueChanged.connect(self._refresh)
        self.cds_premium_freq.currentIndexChanged.connect(self._refresh)
        self.cds_recovery.valueChanged.connect(self._refresh)
        return box

    # -- state ------------------------------------------------------------- #
    def _dates(self) -> tuple[date, date]:
        return self.trade_date.date().toPython(), self.maturity_date.date().toPython()

    def build_trade(self) -> Trade | None:
        """Return the currently specified trade, or ``None`` if invalid."""
        trade, _error = self._build()
        return trade

    def is_valid(self) -> bool:
        return self.build_trade() is not None

    def _build(self) -> tuple[Trade | None, str]:
        trade_date, maturity_date = self._dates()
        if maturity_date <= trade_date:
            return None, "Maturity date must be after the trade date."
        notional = self.notional.value()
        if notional <= 0.0:
            return None, "Notional must be positive."
        trade_id = self.trade_id.text().strip()
        if not trade_id:
            return None, "Trade ID is required."

        index = self.product.currentIndex()
        if index == 0:
            return self._build_irs(trade_id, notional, trade_date, maturity_date), ""
        if index == 1:
            return self._build_fx(trade_id, notional, trade_date, maturity_date)
        return self._build_cds(trade_id, notional, trade_date, maturity_date)

    def _build_irs(
        self, trade_id: str, notional: float, trade_date: date, maturity_date: date
    ) -> IRS:
        return IRS(
            trade_id=trade_id,
            counterparty_id=self._counterparty_id(),
            notional=notional,
            currency=self.currency.currentText(),
            trade_date=trade_date,
            maturity_date=maturity_date,
            fixed_rate=self.irs_fixed_rate.value() / 100.0,
            direction=SwapDirection(self.irs_direction.currentData()),
            fixed_frequency=Frequency(self.irs_fixed_freq.currentData()),
            float_frequency=Frequency(self.irs_float_freq.currentData()),
            float_spread=self.irs_float_spread.value() / 10_000.0,
        )

    def _build_fx(
        self, trade_id: str, notional: float, trade_date: date, maturity_date: date
    ) -> tuple[FXForward | None, str]:
        base = self.fx_base.currentText()
        quote = self.fx_quote.currentText()
        if base == quote:
            return None, "Base and quote currencies must differ."
        return (
            FXForward(
                trade_id=trade_id,
                counterparty_id=self._counterparty_id(),
                notional=notional,
                currency=base,
                trade_date=trade_date,
                maturity_date=maturity_date,
                base_currency=base,
                quote_currency=quote,
                contract_rate=self.fx_rate.value(),
                direction=FxDirection(self.fx_direction.currentData()),
            ),
            "",
        )

    def _build_cds(
        self, trade_id: str, notional: float, trade_date: date, maturity_date: date
    ) -> tuple[CDS | None, str]:
        reference = self.cds_reference.text().strip()
        if not reference:
            return None, "Reference entity is required."
        return (
            CDS(
                trade_id=trade_id,
                counterparty_id=self._counterparty_id(),
                notional=notional,
                currency=self.currency.currentText(),
                trade_date=trade_date,
                maturity_date=maturity_date,
                reference_entity=reference,
                direction=CdsDirection(self.cds_direction.currentData()),
                spread=self.cds_spread.value() / 10_000.0,
                premium_frequency=Frequency(self.cds_premium_freq.currentData()),
                recovery_rate=self.cds_recovery.value() / 100.0,
            ),
            "",
        )

    def _counterparty_id(self) -> str:
        if self._app_state is not None and self._app_state.counterparty is not None:
            return self._app_state.counterparty.counterparty_id
        return "CP"

    def _refresh(self) -> None:
        trade, error = self._build()
        if trade is not None:
            self.summary.setText(self._describe(trade))
            self.status.setText("<span style='color:#2e7d32'>Valid trade.</span>")
        else:
            self.summary.setText("—")
            self.status.setText(f"<span style='color:#c62828'>{error}</span>")
        if self._app_state is not None:
            self._app_state.set_trade(trade)

    @staticmethod
    def _describe(trade: Trade) -> str:
        lines = [
            f"<b>{trade.product}</b> {trade.trade_id}",
            f"Notional: {trade.notional:,.0f} {trade.currency}",
            f"Tenor: {trade.tenor_years:.2f}y "
            f"({trade.trade_date} → {trade.maturity_date})",
        ]
        if isinstance(trade, IRS):
            lines.append(
                f"{trade.direction.value}, fixed {trade.fixed_rate:.3%}, "
                f"float +{trade.float_spread * 1e4:.0f} bps"
            )
        elif isinstance(trade, FXForward):
            lines.append(
                f"{trade.direction.value} {trade.base_currency}/"
                f"{trade.quote_currency} @ {trade.contract_rate:.4f}"
            )
        elif isinstance(trade, CDS):
            lines.append(
                f"{trade.direction.value} on {trade.reference_entity}, "
                f"{trade.spread * 1e4:.0f} bps, R={trade.recovery_rate:.0%}"
            )
        return "<br>".join(lines)
