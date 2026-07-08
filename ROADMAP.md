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

## v3 — toward v1.0.0

Deepening the analytics to a rounded 1.0. Each item ships with tests and green CI.

1. **Wrong-way risk + FVA** ✅ — exposure-credit correlation tilts CVA
   (`wrong_way_adjusted_ee`), plus a funding valuation adjustment. Both set in
   Preferences and reported in the CVA tab and memo.
2. **New products** — cross-currency swap and swaption (analytic pricers,
   exposure wiring, UI).
3. **Multi-currency collateral** — post/receive collateral in a chosen currency
   with an FX haircut.
4. **Exposure / CVA sensitivities** — DV01, CS01, and FX delta of peak PFE and
   CVA by finite difference over the market (common random numbers).
5. **v1.0.0 release** — cut once the above land.

## Beyond v1.0.0

Further extension points: additional products (options, caps/floors); richer
multi-curve construction (OIS discounting vs projection); other XVA terms
(KVA/MVA); and code-signed, auto-updating release builds (needs a signing
certificate).
