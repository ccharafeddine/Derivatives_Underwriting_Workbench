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
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from duw.domain.instruments import (
    CDS,
    IRS,
    CdsDirection,
    CrossCurrencyDirection,
    CrossCurrencySwap,
    Frequency,
    FxDirection,
    FXForward,
    SwapDirection,
    Swaption,
    SwaptionDirection,
    Trade,
)
from duw.ui.app_state import AppState
from duw.ui.help import control_help

_CURRENCIES = ("USD", "EUR")
_PRODUCTS = (
    "Interest Rate Swap",
    "FX Forward",
    "Credit Default Swap",
    "Swaption",
    "Cross-Currency Swap",
)


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


def _set_combo_data(combo: QComboBox, value: object) -> None:
    """Select the combo item whose stored data equals ``value`` (by value)."""
    for i in range(combo.count()):
        if str(combo.itemData(i)) == str(value):
            combo.setCurrentIndex(i)
            return


class TradeTab(QWidget):
    """Term-sheet form producing a validated :class:`Trade`."""

    def __init__(self, app_state: AppState | None = None) -> None:
        super().__init__()
        self._app_state = app_state
        self._build_ui()
        if app_state is not None:
            app_state.bookChanged.connect(self._refresh_book)
        self._refresh()
        self._refresh_book()

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

        self.product.setToolTip(control_help("product"))
        self.notional.setToolTip(control_help("notional"))
        self.currency.setToolTip(control_help("currency"))
        self.trade_date.setToolTip(control_help("trade_date"))
        self.maturity_date.setToolTip(control_help("maturity_date"))

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_irs_page())
        self.stack.addWidget(self._build_fx_page())
        self.stack.addWidget(self._build_cds_page())
        self.stack.addWidget(self._build_swaption_page())
        self.stack.addWidget(self._build_xccy_page())
        form.addRow(self.stack)

        splitter.addWidget(form_panel)

        summary_panel = QWidget()
        summary_layout = QVBoxLayout(summary_panel)
        summary_layout.addWidget(QLabel("<b>Proposed trade</b>"))
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setObjectName("trade_summary")
        summary_layout.addWidget(self.summary)
        self.status = QLabel()
        self.status.setObjectName("trade_status")
        self.status.setWordWrap(True)
        summary_layout.addWidget(self.status)
        summary_layout.addWidget(self._build_book_box())
        summary_layout.addStretch(1)
        splitter.addWidget(summary_panel)
        splitter.setSizes([560, 400])

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

    def _build_book_box(self) -> QGroupBox:
        box = QGroupBox("Existing book (nets against the proposed trade)")
        layout = QVBoxLayout(box)
        self.book_list = QListWidget()
        self.book_list.setMaximumHeight(120)
        layout.addWidget(self.book_list)
        row = QHBoxLayout()
        self.add_book_btn = QPushButton("Add current to book")
        self.remove_book_btn = QPushButton("Remove selected")
        self.clear_book_btn = QPushButton("Clear")
        self.add_book_btn.clicked.connect(self._on_add_to_book)
        self.remove_book_btn.clicked.connect(self._on_remove_from_book)
        self.clear_book_btn.clicked.connect(self._on_clear_book)
        for btn in (self.add_book_btn, self.remove_book_btn, self.clear_book_btn):
            row.addWidget(btn)
        layout.addLayout(row)
        return box

    # -- book -------------------------------------------------------------- #
    def _on_add_to_book(self) -> None:
        trade = self.build_trade()
        if trade is not None and self._app_state is not None:
            self._app_state.add_to_book(trade)

    def _on_remove_from_book(self) -> None:
        row = self.book_list.currentRow()
        if row >= 0 and self._app_state is not None:
            self._app_state.remove_from_book(row)

    def _on_clear_book(self) -> None:
        if self._app_state is not None:
            self._app_state.clear_book()

    def _refresh_book(self) -> None:
        trades = self._app_state.book if self._app_state is not None else []
        self.book_list.clear()
        for trade in trades:
            self.book_list.addItem(self._book_label(trade))
        has = len(trades) > 0
        self.remove_book_btn.setEnabled(has)
        self.clear_book_btn.setEnabled(has)

    @staticmethod
    def _book_label(trade: Trade) -> str:
        return (
            f"{trade.product}  {trade.notional:,.0f} {trade.currency}"
            f"  ·  {trade.tenor_years:.1f}y"
        )

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
        self.irs_fixed_rate.setToolTip(control_help("fixed_rate"))
        self.irs_direction.setToolTip(control_help("direction"))
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

    def _build_swaption_page(self) -> QWidget:
        box = QGroupBox("Swaption terms (maturity date = option expiry)")
        form = QFormLayout(box)
        self.swpt_strike = _rate_spin(4.3, " %")
        self.swpt_direction = QComboBox()
        self.swpt_direction.addItem("Payer", SwaptionDirection.PAYER)
        self.swpt_direction.addItem("Receiver", SwaptionDirection.RECEIVER)
        self.swpt_tenor = QDoubleSpinBox()
        self.swpt_tenor.setRange(0.25, 50.0)
        self.swpt_tenor.setDecimals(2)
        self.swpt_tenor.setSuffix(" y")
        self.swpt_tenor.setValue(5.0)
        self.swpt_vol = _rate_spin(20.0, " %", decimals=1)
        self.swpt_vol.setRange(0.1, 200.0)
        self.swpt_freq = _frequency_combo(Frequency.ANNUAL)
        self.swpt_bought = QCheckBox("We hold the option (bought)")
        self.swpt_bought.setChecked(True)
        form.addRow("Strike rate", self.swpt_strike)
        form.addRow("Direction", self.swpt_direction)
        form.addRow("Underlying tenor", self.swpt_tenor)
        form.addRow("Swap-rate vol", self.swpt_vol)
        form.addRow("Underlying frequency", self.swpt_freq)
        form.addRow("", self.swpt_bought)
        for w in (self.swpt_strike, self.swpt_tenor, self.swpt_vol):
            w.valueChanged.connect(self._refresh)
        self.swpt_direction.currentIndexChanged.connect(self._refresh)
        self.swpt_freq.currentIndexChanged.connect(self._refresh)
        self.swpt_bought.toggled.connect(self._refresh)
        return box

    def _build_xccy_page(self) -> QWidget:
        box = QGroupBox("Cross-currency swap terms (base leg uses Currency above)")
        form = QFormLayout(box)
        self.xccy_base_rate = _rate_spin(4.3, " %")
        self.xccy_foreign_ccy = QComboBox()
        self.xccy_foreign_ccy.addItems(_CURRENCIES)
        self.xccy_foreign_ccy.setCurrentText("EUR")
        self.xccy_foreign_notional = _money_spin(9_000_000.0)
        self.xccy_foreign_rate = _rate_spin(3.3, " %")
        self.xccy_direction = QComboBox()
        self.xccy_direction.addItem("Receive base", CrossCurrencyDirection.RECEIVE_BASE)
        self.xccy_direction.addItem("Pay base", CrossCurrencyDirection.PAY_BASE)
        self.xccy_freq = _frequency_combo(Frequency.ANNUAL)
        self.xccy_exchange = QCheckBox("Exchange notionals at maturity")
        self.xccy_exchange.setChecked(True)
        form.addRow("Base fixed rate", self.xccy_base_rate)
        form.addRow("Foreign currency", self.xccy_foreign_ccy)
        form.addRow("Foreign notional", self.xccy_foreign_notional)
        form.addRow("Foreign fixed rate", self.xccy_foreign_rate)
        form.addRow("Direction", self.xccy_direction)
        form.addRow("Frequency", self.xccy_freq)
        form.addRow("", self.xccy_exchange)
        for w in (
            self.xccy_base_rate,
            self.xccy_foreign_notional,
            self.xccy_foreign_rate,
        ):
            w.valueChanged.connect(self._refresh)
        self.xccy_foreign_ccy.currentIndexChanged.connect(self._refresh)
        self.xccy_direction.currentIndexChanged.connect(self._refresh)
        self.xccy_freq.currentIndexChanged.connect(self._refresh)
        self.xccy_exchange.toggled.connect(self._refresh)
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
        if index == 2:
            return self._build_cds(trade_id, notional, trade_date, maturity_date)
        if index == 3:
            return (
                self._build_swaption(trade_id, notional, trade_date, maturity_date),
                "",
            )
        return self._build_xccy(trade_id, notional, trade_date, maturity_date)

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

    def _build_swaption(
        self, trade_id: str, notional: float, trade_date: date, maturity_date: date
    ) -> Swaption:
        return Swaption(
            trade_id=trade_id,
            counterparty_id=self._counterparty_id(),
            notional=notional,
            currency=self.currency.currentText(),
            trade_date=trade_date,
            maturity_date=maturity_date,
            strike=self.swpt_strike.value() / 100.0,
            direction=SwaptionDirection(self.swpt_direction.currentData()),
            underlying_tenor_years=self.swpt_tenor.value(),
            volatility=self.swpt_vol.value() / 100.0,
            underlying_frequency=Frequency(self.swpt_freq.currentData()),
            bought=self.swpt_bought.isChecked(),
        )

    def _build_xccy(
        self, trade_id: str, notional: float, trade_date: date, maturity_date: date
    ) -> tuple[CrossCurrencySwap | None, str]:
        base = self.currency.currentText()
        foreign = self.xccy_foreign_ccy.currentText()
        if base == foreign:
            return None, "Base and foreign currencies must differ."
        return (
            CrossCurrencySwap(
                trade_id=trade_id,
                counterparty_id=self._counterparty_id(),
                notional=notional,
                currency=base,
                trade_date=trade_date,
                maturity_date=maturity_date,
                foreign_currency=foreign,
                foreign_notional=self.xccy_foreign_notional.value(),
                base_rate=self.xccy_base_rate.value() / 100.0,
                foreign_rate=self.xccy_foreign_rate.value() / 100.0,
                direction=CrossCurrencyDirection(self.xccy_direction.currentData()),
                frequency=Frequency(self.xccy_freq.currentData()),
                exchange_notional=self.xccy_exchange.isChecked(),
            ),
            "",
        )

    def load_trade(self, trade: Trade) -> None:
        """Populate the form from an existing :class:`Trade` (e.g. an example)."""
        self.trade_id.setText(trade.trade_id)
        self.notional.setValue(trade.notional)
        self.trade_date.setDate(
            QDate(trade.trade_date.year, trade.trade_date.month, trade.trade_date.day)
        )
        self.maturity_date.setDate(
            QDate(
                trade.maturity_date.year,
                trade.maturity_date.month,
                trade.maturity_date.day,
            )
        )
        if isinstance(trade, IRS):
            self.product.setCurrentIndex(0)
            self.currency.setCurrentText(trade.currency)
            self.irs_fixed_rate.setValue(trade.fixed_rate * 100.0)
            _set_combo_data(self.irs_direction, trade.direction)
            _set_combo_data(self.irs_fixed_freq, trade.fixed_frequency)
            _set_combo_data(self.irs_float_freq, trade.float_frequency)
            self.irs_float_spread.setValue(trade.float_spread * 1e4)
        elif isinstance(trade, FXForward):
            self.product.setCurrentIndex(1)
            self.fx_base.setCurrentText(trade.base_currency)
            self.fx_quote.setCurrentText(trade.quote_currency)
            self.fx_rate.setValue(trade.contract_rate)
            _set_combo_data(self.fx_direction, trade.direction)
        elif isinstance(trade, CDS):
            self.product.setCurrentIndex(2)
            self.currency.setCurrentText(trade.currency)
            self.cds_reference.setText(trade.reference_entity)
            _set_combo_data(self.cds_direction, trade.direction)
            self.cds_spread.setValue(trade.spread * 1e4)
            _set_combo_data(self.cds_premium_freq, trade.premium_frequency)
            self.cds_recovery.setValue(trade.recovery_rate * 100.0)
        elif isinstance(trade, Swaption):
            self.product.setCurrentIndex(3)
            self.currency.setCurrentText(trade.currency)
            self.swpt_strike.setValue(trade.strike * 100.0)
            _set_combo_data(self.swpt_direction, trade.direction)
            self.swpt_tenor.setValue(trade.underlying_tenor_years)
            self.swpt_vol.setValue(trade.volatility * 100.0)
            _set_combo_data(self.swpt_freq, trade.underlying_frequency)
            self.swpt_bought.setChecked(trade.bought)
        elif isinstance(trade, CrossCurrencySwap):
            self.product.setCurrentIndex(4)
            self.currency.setCurrentText(trade.currency)
            self.xccy_base_rate.setValue(trade.base_rate * 100.0)
            self.xccy_foreign_ccy.setCurrentText(trade.foreign_currency)
            self.xccy_foreign_notional.setValue(trade.foreign_notional)
            self.xccy_foreign_rate.setValue(trade.foreign_rate * 100.0)
            _set_combo_data(self.xccy_direction, trade.direction)
            _set_combo_data(self.xccy_freq, trade.frequency)
            self.xccy_exchange.setChecked(trade.exchange_notional)
        self._refresh()

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
        self.add_book_btn.setEnabled(trade is not None)
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
        elif isinstance(trade, Swaption):
            side = "bought" if trade.bought else "sold"
            lines.append(
                f"{side} {trade.direction.value} swaption, strike "
                f"{trade.strike:.3%}, {trade.underlying_tenor_years:.1f}y "
                f"underlying, vol {trade.volatility:.1%}"
            )
        elif isinstance(trade, CrossCurrencySwap):
            lines.append(
                f"{trade.direction.value}: {trade.base_rate:.3%} {trade.currency} "
                f"vs {trade.foreign_rate:.3%} {trade.foreign_currency} "
                f"({trade.foreign_notional:,.0f} {trade.foreign_currency})"
            )
        return "<br>".join(lines)
