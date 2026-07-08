"""Application entry point and main window wiring.

Builds the :class:`QApplication` and shows the :class:`MainWindow` (defined in
:mod:`duw.ui.main_window`). Run with ``python -m duw.app``.
"""

from __future__ import annotations

import sys

from duw import __version__

__all__ = ["main", "selftest"]


def selftest() -> int:
    """Run a headless end-to-end analysis and exit — verifies a frozen bundle.

    Exercises the numeric pipeline plus the plotly and reportlab report paths
    (the heavy bundled dependencies) without needing a display, so a packaged
    build can be checked with ``DerivativesUnderwritingWorkbench --selftest``.
    """
    import tempfile
    from datetime import date
    from pathlib import Path

    from duw.data.loader import load_seed_counterparties
    from duw.domain.instruments import IRS, NettingSet, SwapDirection
    from duw.pipeline.orchestrator import RunConfig, run_pipeline
    from duw.reports.memo import render_memo_html, write_memo_pdf

    counterparty = {c.counterparty_id: c for c in load_seed_counterparties()}["CP001"]
    trade = IRS(
        trade_id="SELFTEST",
        counterparty_id="CP001",
        notional=10_000_000.0,
        currency="USD",
        trade_date=date(2025, 6, 30),
        maturity_date=date(2030, 6, 30),
        fixed_rate=0.043,
        direction=SwapDirection.PAY_FIXED,
    )
    results = run_pipeline(
        counterparty,
        NettingSet("NS", "CP001", ()),
        trade,
        RunConfig(n_paths=300, n_steps=5, seed=1),
    )
    html = render_memo_html(results, include_charts=True)  # exercises plotly
    with tempfile.TemporaryDirectory() as tmp:
        pdf = write_memo_pdf(results, Path(tmp) / "memo.pdf", include_charts=False)
        pdf_ok = pdf.exists() and pdf.read_bytes().startswith(b"%PDF")
    print(
        f"self-test OK (v{__version__}): peak PFE "
        f"{results.exposure.peak_pfe:,.0f}, recommendation "
        f"{results.memo.recommendation}, memo HTML {len(html):,} bytes, "
        f"PDF {'ok' if pdf_ok else 'FAILED'}"
    )
    return 0 if pdf_ok else 1


def main(argv: list[str] | None = None) -> int:
    """Launch the application. Returns the Qt event-loop exit code."""
    args = argv if argv is not None else sys.argv
    if "--selftest" in args:
        return selftest()

    # Qt is imported lazily so ``--selftest`` needs no display.
    from PySide6.QtWidgets import QApplication

    from duw.config import KEY_THEME, AppSettings
    from duw.ui.main_window import MainWindow
    from duw.ui.theme import apply_theme

    app = QApplication.instance() or QApplication(args)
    app.setApplicationName("Derivatives Underwriting Workbench")
    app.setApplicationVersion(__version__)

    apply_theme(app, AppSettings().get_str(KEY_THEME))

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
