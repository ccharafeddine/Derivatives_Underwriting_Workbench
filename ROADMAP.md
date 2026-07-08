# Roadmap

The v1 (below) reconstructs the full counterparty-credit underwriting workflow.
**v2** turns it into a genuinely useful learning and scenario-testing tool with
a packaged, downloadable release. Everything stays within the honest framing:
educational, synthetic/public data, simplified methodologies — not a production
risk system.

## v1 — shipped

Trade → counterparty credit (Merton / Altman / rating) → Monte Carlo exposure
(EE / EPE / PFE) → collateral (CSA) → CVA / DVA / BCVA → limit check →
underwriting memo (HTML / PDF / PPTX) → deal pipeline. PySide6 desktop UI,
background worker, reproducible runs, 139 headless tests, CI on Python 3.11/3.12.

## v2 — shipped (v0.2.0)

All four tracks below are complete and released as **v0.2.0**. Each shipped with
tests and green CI (ruff + headless pytest on Python 3.11/3.12).

### 1. Portfolio book + scenario stress testing ✅

- **Existing-trades book.** Build a real netting set of existing trades in the
  UI so the netting benefit and *incremental* limit logic (already implemented
  and tested) actually work end to end, instead of always starting from an empty
  book. This is the single biggest jump in usefulness.
- **Scenario stress testing.** Apply market shocks — parallel rate shift, curve
  steepen / flatten, FX move, credit-spread widening — and re-run to compare
  base vs stressed exposure, CVA, and limit utilization side by side. The core
  "scenario sandbox" and the most analyst-real feature.

### 2. Learn mode + guided examples ✅

- Inline explanations of every metric (EE, EPE, PFE, CVA / DVA, DtD, CSA, MPoR)
  via info tooltips and a glossary panel.
- A set of ready-made example deals (investment-grade swap, distressed CDS, a
  breaching trade, a collateralized book) and a short first-run walkthrough, so
  the app is self-teaching for someone new to the workflow.

### 3. Editable market data + live financials ✅

- In-app curve / FX / credit-spread editor so users test their own market
  scenarios and see how the drivers move exposure and CVA.
- Wire the existing (offline-safe) yfinance pull into the counterparty tab so a
  real public-company ticker can populate the financials for Merton / Altman,
  always degrading to synthetic data.

### 4. Packaged release ✅

- A working PyInstaller build (bundling QtWebEngine and the synthetic data is
  the tricky part), verified to launch and run a full analysis.
- Windows `.msi` and macOS `.dmg` per [PACKAGING.md](PACKAGING.md); code signing
  and notarization remain a documented follow-up.

## Beyond v2

Deliberately deferred extension points: wrong-way risk in exposure and CVA;
additional products (cross-currency swaps, swaptions, options); funding and
other XVA terms; multi-currency collateral; exposure/CVA sensitivities
(DV01 / CS01); richer curve construction; and code-signed, auto-updating
release builds.
