"""Optional public-financials fetch via yfinance.

Best-effort helper that populates a :class:`Financials` from a public issuer's
filings so Merton/Altman can run on a real name. It is strictly optional and
never required: ``yfinance`` is imported lazily, every call is wrapped in
``try/except``, the resolved issuer is sanity-checked against the requested
ticker, and any failure (bad ticker, no network, missing fields) degrades to
``None`` so the caller falls back to the bundled synthetic data.

There are no network calls at import time, and none unless a non-empty ticker is
passed. Pure Python; no Qt.
"""

from __future__ import annotations

from duw.domain.counterparty import Financials


def _first_positive(*values: object) -> float | None:
    """Return the first value that is a positive finite number, else ``None``."""
    for v in values:
        if isinstance(v, (int, float)) and v == v and v > 0.0:
            return float(v)
    return None


def fetch_financials(
    ticker: str | None,
    *,
    equity_volatility: float = 0.30,
    currency: str = "USD",
) -> Financials | None:
    """Fetch financials for ``ticker`` via yfinance, or ``None`` on any failure.

    ``equity_volatility`` is supplied by the caller (a realized/implied estimate)
    since it is not a balance-sheet item. Amounts are returned in the issuer's
    reporting units as provided by the data source.
    """
    if not ticker or not ticker.strip():
        return None

    try:
        import yfinance as yf  # lazy: no network or hard dep at import time

        tk = yf.Ticker(ticker)
        info = getattr(tk, "info", {}) or {}

        # Sanity-check the ticker resolved to the intended issuer.
        resolved = str(info.get("symbol", "")).upper()
        if resolved and resolved != ticker.strip().upper():
            return None

        balance = tk.balance_sheet
        income = tk.financials
        if balance is None or balance.empty or income is None or income.empty:
            return None

        def bs(*keys: str) -> float | None:
            for key in keys:
                if key in balance.index:
                    return _first_positive(balance.loc[key].iloc[0])
            return None

        def isr(*keys: str) -> float | None:
            for key in keys:
                if key in income.index:
                    return _first_positive(income.loc[key].iloc[0])
            return None

        total_assets = bs("Total Assets")
        total_liabilities = bs("Total Liabilities Net Minority Interest", "Total Liab")
        current_assets = bs("Current Assets", "Total Current Assets")
        current_liabilities = bs("Current Liabilities", "Total Current Liabilities")
        retained_earnings = bs("Retained Earnings")
        ebit = isr("EBIT", "Operating Income")
        sales = isr("Total Revenue", "Operating Revenue")
        market_equity = _first_positive(info.get("marketCap"))

        required = (
            total_assets,
            total_liabilities,
            current_assets,
            current_liabilities,
            retained_earnings,
            ebit,
            sales,
            market_equity,
        )
        if any(v is None for v in required):
            return None

        return Financials(
            total_assets=total_assets,
            total_liabilities=total_liabilities,
            current_assets=current_assets,
            current_liabilities=current_liabilities,
            retained_earnings=retained_earnings,
            ebit=ebit,
            sales=sales,
            market_equity=market_equity,
            equity_volatility=equity_volatility,
            currency=currency,
        )
    except Exception:
        # Any failure at all (import, network, schema drift) degrades to None.
        return None
