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

## v3 — shipped (v1.0.0)

Deepening the analytics to a rounded 1.0. All items shipped with tests and green
CI, released as **v1.0.0**.

1. **Wrong-way risk + FVA** ✅ — exposure-credit correlation tilts CVA
   (`wrong_way_adjusted_ee`), plus a funding valuation adjustment. Both set in
   Preferences and reported in the CVA tab and memo.
2. **New products** ✅ — European swaption (Black on the forward swap rate) and
   fixed-for-fixed cross-currency swap (FX-sensitive, two-curve), each with a
   pricer, exposure wiring, Trade-tab page, memo terms, and deal-store support.
3. **Multi-currency collateral** ✅ — collateral posted in a chosen currency with
   an FX haircut that discounts its value; set in the Collateral tab.
4. **Exposure / CVA sensitivities** ✅ — DV01, CS01, and FX delta of peak PFE and
   CVA by finite difference over the market (common random numbers), in a
   dedicated tab computed off-thread.
5. **v1.0.0 release** ✅ — version 1.0.0, packaged bundle rebuilt and verified
   (`--selftest` + GUI launch), GitHub Release cut.

## v4 — shipped (v1.1.0)

Turning the Simulator from a scenario picker into a taught course. Shipped with
tests and green CI, released as **v1.1.0**.

1. **The underwriting campaign** ✅ — 17 stages in dependency order
   (`scenario/campaign.py`), each unlocked by clearing the one before it, with
   medals and progress persisted to `~/.duw/campaign.json`
   (`store/progress.py`). Stage order is the teaching order: the core decision,
   then reading the credit evidence unaided, netting and the committee's limit,
   calibrating the CSA, each product in turn, the funding and own-credit legs,
   wrong-way risk, the sensitivity report, and an unaided capstone.
2. **Full product and XVA coverage** ✅ — new bundled scenarios for credit
   default swaps, collateral mechanics (threshold / MTA / initial margin /
   MPoR), FVA and DVA, and DV01 / CS01 / FX delta, so the campaign teaches every
   product and every adjustment the quantitative layer implements.
3. **Guided stages** ✅ — a stage that introduces a mechanism is coached, with
   the author's recommended decision and a predict-then-reveal question that
   withholds the analytics until the learner commits to an expectation; a stage
   that applies a known mechanism is unaided, and the capstone always is.
4. **Scoring and debrief** ✅ — every run is scored against the scenario's own
   best play (`scenario/coaching.py`) and graded on four desk skills, with a
   round-by-round attribution of where ground was gained or lost.
5. **Live decision controls** ✅ — the CSA threshold, MTA, initial margin,
   margin period of risk and limit are dials that re-price the deal as they
   move, with the exposure profile and consequence table responding before the
   decision is committed.
6. **v1.1.0 release** — version bumped to 1.1.0, README and About brought up to
   date with fresh screenshots, and the packaged bundle rebuilt and verified:
   `--selftest` green from the bundle (peak PFE 540,767, unchanged from v1.0.0,
   campaign 17/17 stages) and the GUI launches. Building it caught `duw.spec`
   dropping every campaign scenario, fixed here. Still to do: cut the GitHub
   Release so the in-app update check reports correctly.

## Beyond v1.1.0

Further extension points: additional products (options, caps/floors); richer
multi-curve construction (OIS discounting vs projection); other XVA terms
(KVA/MVA); interactive concept labs standing outside the deal flow; instructor
mode for authoring and sharing scenarios and reviewing learner decisions; and
code-signed, auto-updating release builds (needs a signing certificate).
