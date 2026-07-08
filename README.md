# Derivatives Underwriting Workbench

[![CI](https://github.com/ccharafeddine/Derivatives_Underwriting_Workbench/actions/workflows/ci.yml/badge.svg)](https://github.com/ccharafeddine/Derivatives_Underwriting_Workbench/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Qt](https://img.shields.io/badge/UI-PySide6%20%2F%20Qt6-41cd52.svg)](https://doc.qt.io/qtforpython/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Purpose-built educational software that teaches the OTC derivatives
counterparty-credit underwriting workflow** — suitable for a Master's-level
derivatives course or serious self-study. It walks you, step by step, through
the decision a corporate derivatives underwriting desk makes on every proposed
trade, and makes the mechanics of each step visible and manipulable so the
concepts stick.

Give it a proposed trade — an interest rate swap, FX forward, credit default
swap, swaption, or cross-currency swap — and it quantifies the counterparty
exposure the trade creates, prices in the counterparty's credit risk
(CVA/DVA/FVA, with a wrong-way-risk option), checks it against limits, models the
effect of collateral, reports risk sensitivities, and produces an underwriting
memo with a recommendation. Each stage is exposed rather than black-boxed, so
you can change an input and watch the output respond.

Built with PySide6/Qt6. Runs fully offline on a bundled synthetic market
snapshot; can optionally pull public-company financials for counterparty credit
analysis.

> **Synthetic data is a design choice, not a shortcoming.** This is teaching
> software, so it runs on synthetic and instructor-authorable data (plus
> optional public financials) on purpose: controllable, reproducible scenarios
> let a lesson isolate one concept at a time — hold everything fixed and move
> only the credit spread, or only the correlation, and see exactly what changes.
> It is not a production risk system, executes no trades, and is not affiliated
> with or endorsed by any financial institution. Nothing it produces is
> investment, credit, or legal advice.

---

## What it does

A corporate derivatives underwriting desk answers one question for every
proposed trade: *should we take this counterparty exposure, at what limit, with
what collateral, and what does it do to our book?* This app models that
decision end to end — and its tabs are arranged as a learning progression, each
teaching one concept and building on the ones before it: from the trade and
counterparty, to exposure, to collateral and limits, to the credit-risk pricing
(CVA/DVA/FVA and wrong-way risk) that sits on top. A **Teaches** note on each
section names the concept it targets.

### 1. Trade

*Teaches: netting — why exposure is measured on the net position under an ISDA
master, not trade by trade.*

Capture a proposed trade as a term sheet: product (interest rate swap, FX
forward, credit default swap, European swaption, or cross-currency swap),
notional, tenor, direction, and the economic terms for each leg. The trade is
added to the counterparty's existing netting set so exposure is measured on the
net position, the way an ISDA master agreement actually works.

![Trade input tab](docs/images/trade.png)

### 2. Counterparty

*Teaches: distance-to-default and PD — how a structural (Merton/KMV) model and
a balance-sheet score turn equity and financials into a default probability.*

Assess the counterparty's creditworthiness. A KMV-style Merton model derives a
distance-to-default and default probability from equity value and volatility; an
Altman Z-score summarizes balance-sheet health; the two are mapped to an
internal rating grade and a probability-of-default term structure. Enter a public
ticker and **Fetch** pulls the company's financials via yfinance (offline-safe,
degrading to synthetic data); private names come from the bundled synthetic set.

![Counterparty tab](docs/images/counterparty.png)

### 3. Market

*Teaches: the risk drivers — how curves, FX spots, and credit spreads feed
pricing, so you can change one driver and see exposure and CVA respond.*

Inspect and edit the market the trade is priced against: zero curves by currency,
FX spots, and CDS spread curves by issuer. Change a rate, spot, or spread and
Apply, and the next analysis prices against your values — a quick way to test how
the drivers move exposure and CVA (or reset to the bundled snapshot).

![Market tab](docs/images/market.png)

### 4. Exposure

*Teaches: expected exposure vs potential future exposure — how a distribution of
future MtM becomes EE, EPE, and PFE, and why the profile has the shape it does.*

The core engine. Monte Carlo simulation evolves the trade's risk factors
(interest rates, FX, credit spreads) forward over the trade's life, reprices the
netting set on every path at every date, and reads off the exposure profile:

- **Expected Exposure (EE)** and **Expected Positive Exposure (EPE)**
- **Potential Future Exposure (PFE)** at 95% and 99%, and **peak PFE**
- The full exposure cone over time

![Exposure tab](docs/images/exposure.png)

### 5. Limits

*Teaches: limit utilization and incremental exposure — why the marginal PFE a
new trade adds to an existing book, not its standalone risk, is what matters.*

Check the trade against a per-counterparty credit limit. The netting set is
aggregated across existing and proposed trades to show current utilization,
remaining headroom, the **incremental** exposure the new trade adds, and a clear
flag when it would breach the limit.

![Limits tab](docs/images/limits.png)

### 6. Collateral

*Teaches: collateralized vs uncollateralized exposure — how a CSA cuts exposure,
and why the margin period of risk leaves residual gap risk that collateral can't
remove.*

Model a Credit Support Annex — threshold, minimum transfer amount, initial
margin, and margin period of risk — and see how much it reduces exposure.
Collateralized and uncollateralized PFE are shown side by side so the risk
mitigation is explicit. Collateral posted in a different currency than the
exposure carries an FX haircut, so you can see why cross-currency collateral
mitigates less.

![Collateral tab](docs/images/collateral.png)

### 7. CVA

*Teaches: CVA/DVA/FVA and wrong-way risk — how expected exposure, a survival
curve, and discounting combine into the price of default risk, and how that
price moves when exposure and credit quality are correlated.*

Compute the Credit Valuation Adjustment: the market value of the counterparty's
default risk, built from the expected-exposure profile, the counterparty's
survival curve, and discounting. The symmetric own-credit adjustment (DVA), the
bilateral net (BCVA), and a funding valuation adjustment (FVA) are reported
alongside. A **wrong-way risk** correlation (set in Preferences) tilts expected
exposure toward its higher paths, raising CVA when exposure rises with default
risk.

![CVA tab](docs/images/cva.png)

### 8. Scenario

*Teaches: stress sensitivity — how exposure, CVA, and limit use respond when the
market moves, via a hands-on sandbox of shocks compared against the base case.*

Stress test the proposed trade. Apply market shocks — a parallel rate shift, a
curve steepener/flattener, an FX move, and credit-spread widening (with named
presets like *Risk-off* and *Credit crunch*) — and re-run to compare base vs
stressed exposure, CVA, and limit utilization side by side, with the two
exposure profiles overlaid.

![Scenario tab](docs/images/scenario.png)

### 9. Sensitivities

*Teaches: risk sensitivities and common random numbers — what DV01, CS01, and FX
delta mean, and why reusing the Monte Carlo seed is what makes a finite-
difference bump readable at all.*

Bump-and-reprice risk sensitivities of the headline numbers: DV01 (per 1bp
parallel rate move) and FX delta (per 1% FX move) of peak PFE and CVA, and CS01
(per 1bp credit-spread move) of CVA. Every bump reuses the same Monte Carlo seed
(common random numbers) so the difference reflects the market move, not
simulation noise.

![Sensitivities tab](docs/images/sensitivities.png)

### 10. Memo

*Teaches: the underwriting decision — how the separate metrics come together
into a single reasoned recommendation, with plain-English commentary on each.*

Generate a one-page underwriting memo: trade summary, counterparty snapshot,
exposure metrics, collateral effect, CVA, limit impact, and a recommendation.
Plain-English commentary is generated across every section by an interpretation
engine. Exportable as HTML and PDF, with an optional client-facing slide deck.

![Memo tab](docs/images/memo.png)

### 11. Pipeline

*Teaches: the approval lifecycle — how a deal moves through underwriting stages,
and that a desk juggles many trades at different stages at once.*

Track multiple transactions through their approval stages — Requested → Under
review → Credit approved → Documented → Executed — since underwriting means
juggling many deals at different stages at once. Runs are saved locally and can
be reopened.

![Pipeline board](docs/images/pipeline.png)

---

## How it teaches

The learning scaffolding is a first-class part of the app, not incidental UI:

- **One-click example deals** (**Help → Load Example**) — an investment-grade
  swap, a distressed-name CDS, a limit-breaching trade, and a netted book. Each
  loads a complete, runnable scenario so a newcomer can go from launch to a full
  analysis in a single click and start from a worked example rather than a blank
  form.
- **Glossary** (**Help → Glossary**) — a plain-English definition of every term
  the app reports (EE, EPE, PFE, CVA/DVA/FVA, DtD, CSA, MPoR, and more).
- **Metric tooltips** — the same glossary definitions attach to metric labels
  throughout the UI, so the explanation is one hover away from the number.
- **Scenario sandbox** (the Scenario tab) — a hands-on space to apply market
  shocks and watch exposure, CVA, and limit utilization move against the base
  case, so cause and effect are visible rather than asserted.
- **Editable market inputs** (the Market tab) — change a curve, spot, or spread
  and re-run to see how the drivers move the outputs.
- **Reproducibility** — every run saves its Monte Carlo seed and full
  configuration, so a scenario reproduces exactly and can be shared or revisited.

---

## Pipeline architecture

A single underwriting run executes twelve steps sequentially. Each step reads
all prior results and stores its outputs in a shared `AnalysisResults`
dataclass. The pipeline runs on a background thread with a live progress bar;
report generation happens on demand.

```
Step  0  Load market snapshot        Curves, FX rates, credit spreads, vols
Step  1  Build trade + netting set    Proposed trade added to counterparty's set
Step  2  Assess counterparty credit   Merton DtD, Altman Z, rating, PD curve
Step  3  Simulate risk factors        Monte Carlo paths (rates / FX / spread)
Step  4  Reprice across time grid      MtM cube across trades, paths, and dates
Step  5  Aggregate netting set         Net MtM per path and date
Step  6  Compute exposure profile      EE, EPE, PFE (95/99), peak PFE, cone
Step  7  Apply collateral (CSA)        Collateralized vs uncollateralized exposure
Step  8  Compute CVA / DVA / BCVA      EE profile x marginal PD x discounting
Step  9  Check limits                  Utilization, headroom, incremental, breach
Step 10  Interpret + generate memo     Commentary and recommendation
Step 11  Save outputs                  Run config (JSON) + HTML/PDF/PPTX reports
```

Every run is reproducible: the Monte Carlo seed and the full run configuration
are saved with the outputs.

---

## Tech stack

- **Python 3.11+**, **PySide6 / Qt6** (menu-bar desktop UI, `QSplitter` panels)
- **numpy / pandas / scipy** for pricing, simulation, and credit models
- **plotly** (+ **kaleido**) for charts; **reportlab** and **python-pptx** for reports
- **pyarrow / parquet** for market-data caching
- **yfinance** (optional) for public-company financials
- **ruff** and **pytest** for linting and headless testing

Numeric models (`pricing/`, `risk/`, `credit/`, `pipeline/`) are pure Python
with no Qt dependency and are unit-tested headlessly. Qt is confined to the UI,
the app entry point, and the background worker.

---

## Getting started

```bash
# create and activate a virtual environment, then:
pip install -e ".[dev]"

# launch the app
python -m duw.app

# run the test suite headlessly
QT_QPA_PLATFORM=offscreen pytest -q

# lint and format
ruff check . && ruff format .
```

The app launches against the bundled synthetic market snapshot and seed
counterparties, so it works with no configuration and no network access. New to
the workflow? **Help → Load Example** loads a ready-made deal (investment-grade
swap, distressed-name CDS, a limit-breaching trade, a netted book) you can run in
one click, **Help → Glossary** explains every term, and each metric shows a
plain-English tooltip on hover. Monte Carlo settings (paths, seed, default LGD)
live under **Settings → Preferences**, the theme toggles under **View → Theme**,
and the disclaimer is in **Help → About**. Saved deals persist locally and reopen
with the same seed, so any run reproduces exactly.

To build a native desktop binary (`.msi` / `.dmg`), see
[PACKAGING.md](PACKAGING.md).

---

## Scope

v1.0.0 covers five products (interest rate swap, FX forward, credit default
swap, European swaption, fixed-for-fixed cross-currency swap); counterparty
credit via Merton and Altman; Monte Carlo exposure with EE/EPE/PFE; collateral
modeling with a CSA, MPoR, and multi-currency FX haircut; CVA, DVA, BCVA, FVA,
and an optional wrong-way-risk tilt; DV01/CS01/FX-delta sensitivities; scenario
stress testing; limit checking; the underwriting memo; and the deal pipeline.

Further quantitative extension points left for later include other XVA terms
(KVA/MVA), additional products (caps/floors), and richer multi-curve
construction (OIS discounting vs projection).

---

## Educational roadmap

These are the app's intended next direction as teaching software. **They are
not built yet** — this section describes future work, not current features.

- **Role-play underwriting simulator.** A proposed deal each round: you assess
  the counterparty, set collateral and limits, and price the trade; then
  simulated time advances, counterparties migrate in credit quality and some
  default, and you live with the consequences of earlier decisions — scored on
  risk-adjusted P&L.
- **Interactive concept labs.** A slider-and-live-chart sandbox for each
  concept: for example, a wrong-way-risk lab where correlation is a slider and
  CVA redraws live, or a collateral lab where threshold, MTA, and MPoR move and
  collateralized PFE responds. The aim is to surface the newer quantitative
  features (FVA, wrong-way risk, sensitivities) as things you manipulate, not
  numbers you read.
- **Instructor mode.** Author and share a scenario — scripted counterparty
  credit paths, a market path, a deal stream, and defaults — and review student
  decisions against it.

---

## Disclaimer

This software is provided for educational and demonstration purposes only. It
uses synthetic and publicly available data, models simplified versions of
real methodologies, and is not affiliated with, endorsed by, or connected to any
bank or financial institution. It does not execute or facilitate trades and
produces no investment, credit, or legal advice. Do not use it for any real
underwriting, trading, or credit decision.
