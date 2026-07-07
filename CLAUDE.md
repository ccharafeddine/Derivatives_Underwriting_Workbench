# CLAUDE.md

Guidance for Claude Code working in this repository. Read this in full at the
start of every session before writing any code.

---

## What this is

**Derivatives Underwriting Workbench** (working name; package `duw`) is a
desktop analytics application that reconstructs the counterparty-credit
underwriting workflow for OTC derivatives — the decision a corporate
derivatives underwriting desk makes when a client wants to enter an interest
rate, FX, or credit derivative trade: *should we take this counterparty
exposure, at what limit, with what collateral, and what does it do to our
book?*

The app takes a proposed trade, quantifies the counterparty exposure it
creates, prices in the counterparty's credit risk, checks it against limits,
and produces an underwriting memo with a recommendation.

### Honest framing (this is load-bearing — keep it true in code and docs)

- This is a **portfolio / educational project**, not a production risk system
  and not affiliated with, endorsed by, or connected to any bank.
- It runs entirely on **synthetic and public data**. There is no proprietary
  data, no live trade feed, no internal credit system.
- It does not execute, book, or route trades. It is an analysis tool.
- Nothing it outputs is investment, credit, or legal advice.
- Do not add copy anywhere (UI, README, comments, memos) that implies this is a
  real bank's system or that it "automates the job." It models the *workflow*.

---

## Tech stack

Mirror the conventions of the author's Portfolio Analyzer app (a PySide6/Qt6
analytics desktop app). This is its architectural sibling, not a novel stack.

- Python 3.11+
- **PySide6 / Qt6** — desktop UI, traditional **menu bar** (File / Edit / View /
  Settings), **not** a frameless minimal shell. `QSplitter` for resizable panels.
- **numpy / pandas / scipy** — all numerics.
- **plotly** (+ **kaleido** for static export in reports) — charts.
- **pyarrow / parquet** — market-data caching.
- **yfinance** — public-company financials for counterparty credit (optional; the
  app must run fully offline from the bundled synthetic snapshot).
- **reportlab** — PDF memos. **python-pptx** — optional client deck.
- Config via a thin `AppSettings` wrapper over `QSettings`.
- Long computations run on a **background `QThread` worker** that emits progress
  signals to a progress bar — never block the UI thread.

Dev tooling: **ruff** (lint + format), **pytest** (headless). Qt tests run with
`QT_QPA_PLATFORM=offscreen`. There is no Rust in this repo, so clippy does not
apply.

---

## Directory layout

```
src/duw/
  app.py                # QApplication entry point + main window wiring
  config.py             # AppSettings over QSettings
  domain/
    instruments.py      # Trade base + IRS, FXForward, CDS dataclasses; NettingSet
    market.py           # MarketSnapshot: yield curves, FX, credit spreads, vols
    counterparty.py     # Counterparty + CreditProfile
    results.py          # AnalysisResults + all sub-result dataclasses
  data/                 # bundled synthetic market snapshot + seed counterparties
  pricing/
    curves.py           # discount curve, interpolation, survival curve bootstrap
    irs.py  fx_forward.py  cds.py
  risk/
    simulators.py       # HW1F rates, GBM FX, mean-reverting credit spread
    exposure.py         # ExposureEngine: MtM cube -> EE/EPE/PFE/peak, profile
    collateral.py       # CSA application (threshold, MTA, IM, MPoR)
    cva.py              # CVA / DVA / BCVA
    limits.py           # netting-set limit checks, incremental exposure
  credit/
    merton.py           # KMV-style distance-to-default and PD
    altman.py           # Altman Z-score
    rating.py           # PD -> internal grade, PD term structure
  pipeline/
    orchestrator.py     # sequential steps -> AnalysisResults
    worker.py           # QThread worker + progress signals
  reports/
    interpreter.py      # plain-English commentary per section
    memo.py             # underwriting memo (HTML + PDF)
    deck.py             # optional PPTX
  ui/
    main_window.py
    tabs/               # trade, counterparty, exposure, limits, collateral, cva, memo, pipeline
    widgets/            # plotly view, result tables, shared controls
  store/
    deals.py            # deal-pipeline persistence (local SQLite or JSON)
tests/
```

Keep this layout. If a session needs a new module, place it in the matching
package rather than creating a new top-level one.

---

## The analysis pipeline

A single underwriting run is a sequential pipeline. Each step reads prior
results and writes into a shared `AnalysisResults` dataclass (same pattern as
Portfolio Analyzer). The orchestrator runs these in order; the worker runs the
orchestrator off-thread with progress.

```
Step 0  Load market snapshot        curves, FX, credit spreads, vols
Step 1  Build trade + netting set   proposed trade added to counterparty's set
Step 2  Assess counterparty credit  Merton DtD, Altman Z, rating, PD term structure
Step 3  Simulate risk factors       Monte Carlo paths (rates / FX / spread)
Step 4  Reprice across time grid     MtM cube: trades x paths x time
Step 5  Aggregate netting set        net MtM per path/time
Step 6  Compute exposure profile     EE, EPE, PFE(95/99), peak PFE, cone
Step 7  Apply collateral (CSA)       collateralized vs uncollateralized exposure
Step 8  Compute CVA / DVA / BCVA     from EE profile x marginal PD x discount
Step 9  Check limits                 utilization, headroom, breach, incremental
Step 10 Interpret + generate memo    commentary + recommendation
Step 11 Save outputs                 run config (JSON, for reproducibility) + reports
```

Every run must be **reproducible**: the Monte Carlo seed and full run
configuration are saved with the outputs, exactly as Portfolio Analyzer saves
its run config as JSON.

---

## Domain glossary (use these terms precisely in code and comments)

- **MtM** — mark-to-market value of a trade to us.
- **Exposure** — max(MtM, 0): what we'd lose if the counterparty defaulted now.
- **Netting set** — trades under one ISDA master that net; exposure is on the
  *net* MtM, not per-trade.
- **EE(t)** — Expected Exposure: mean of positive net MtM at time t across paths.
- **EPE** — Expected Positive Exposure: time-average of EE.
- **PFE(t, α)** — Potential Future Exposure: the α-quantile (e.g. 95%, 99%) of
  positive exposure at t. **Peak PFE** is its max over the trade's life.
- **CVA** — Credit Valuation Adjustment: market value of counterparty default
  risk. Unilateral: `CVA ≈ LGD · Σ_i DF(t_i)·EE(t_i)·mPD(t_{i-1}, t_i)` where
  `mPD` is the marginal default probability over each interval from the survival
  curve. **DVA** is the symmetric own-credit term; **BCVA = CVA − DVA**.
- **CSA** — Credit Support Annex: the collateral agreement. Parameters:
  **threshold** (unsecured amount), **MTA** (minimum transfer amount),
  **IM / IA** (initial margin / independent amount), **MPoR** (margin period of
  risk, e.g. 10 business days — the gap over which collateral can't be called).
- **DtD** — distance-to-default (Merton/KMV). **PD** — probability of default.
  **LGD** — loss given default (`1 − recovery`).
- **Wrong-way risk** — exposure rising as the counterparty's credit worsens
  (correlation between exposure and PD). Out of scope for v1; leave a hook.

---

## Modeling approach (target; simplify only where noted)

- **Discounting / curves**: bootstrap discount factors from the snapshot's zero
  curve; interpolate log-linearly on DFs. Survival curves bootstrapped from CDS
  spreads with a piecewise-constant hazard rate.
- **Pricing** (analytic, curve-based):
  - IRS: PV of fixed leg vs float leg off the discount/forward curve; par swap ≈
    0 MtM at inception (use this as a test).
  - FX forward: covered interest parity; MtM = discounted (contracted forward −
    prevailing forward) × notional.
  - CDS: PV(protection leg) − PV(premium leg) using the survival curve.
- **Risk-factor simulation** (deterministic seed): Hull-White one-factor for the
  short rate (fits the initial curve); GBM for FX spot with drift = rate
  differential; mean-reverting (Ornstein-Uhlenbeck / CIR-style) process for the
  credit spread driving CDS MtM. A Vasicek short rate or shocked-spread
  approximation is an **acceptable v1 fallback** if HW1F calibration is too heavy
  — note it clearly in a docstring if you fall back.
- **Exposure**: reprice the netting set on each path at each grid date → net MtM
  cube → positive part → EE/EPE/PFE percentiles and the profile time series.
- **Collateral**: apply CSA to the net exposure with a simplified MPoR model —
  collateralized exposure is exposure above the threshold accrued over the MPoR
  window, plus IM offset. Report collateralized vs uncollateralized side by side.
- **Counterparty credit**: KMV-style Merton (solve `E = V·N(d1) − D·e^{−rT}·N(d2)`
  and `σ_E·E = σ_V·V·N(d1)` for asset value/vol; `DtD = (ln(V/D)+(μ−½σ_V²)T)/(σ_V√T)`;
  `PD = N(−DtD)`), Altman Z-score from financials, and a PD term structure from
  CDS if present else scaled from Merton/rating. Map PD to an internal grade via
  a lookup table.
- **Limits**: a per-counterparty limit (PFE-based). Utilization = netting-set
  peak PFE / limit; incremental = PFE with the new trade − PFE without; flag a
  breach when the new trade pushes utilization over 100%.

`yfinance` caution (carried from Portfolio Analyzer): validate that a pulled
ticker resolves to the intended issuer before trusting its financials; don't
assume a bare symbol is correct. Always degrade gracefully to synthetic data.

---

## Coding conventions

- Type hints everywhere. Results are frozen `@dataclass`es; the shared
  `AnalysisResults` aggregates them.
- Pure numerics (`pricing/`, `risk/`, `credit/`, `pipeline/`) must have **no Qt
  imports** and be unit-testable headlessly. Qt lives only in `ui/`, `app.py`,
  `pipeline/worker.py`, and `config.py`.
- All Monte Carlo takes an explicit `seed`/`rng`; no global random state.
- No network calls at import time and none on the UI thread. Bundled snapshot is
  the default source; `yfinance` is opt-in and always wrapped in try/except with
  a synthetic fallback.
- Money and rates: be explicit about units (bps vs decimals, notional currency,
  act/360 vs 30/360 day counts) in docstrings.
- Small, composable functions over god-objects. Match the surrounding style.

## Verification gates (run before ending every session)

1. `ruff check . && ruff format --check .` — clean.
2. `QT_QPA_PLATFORM=offscreen pytest -q` — all tests pass headlessly.
3. The session's smoke test (stated per session) runs green.
4. Summarize what changed and paste the verification output.

Do not end a session with failing gates or a broken app launch.

## DO NOT (scope boundaries)

- Do not turn this into a trading, execution, or booking system.
- Do not add cloud API keys, telemetry, accounts, or ads.
- Do not couple to the Portfolio Analyzer repo — this is standalone.
- Do not add products beyond IRS / FX forward / CDS in v1 without being asked.
- Do not implement wrong-way risk, XVA beyond CVA/DVA, or multi-currency
  collateral in v1 — leave hooks, not implementations.
- Do not put real, proprietary, or bank-identifying data anywhere.
- Do not expand a session's stated scope; if you discover adjacent work, note it
  for a future session rather than doing it now.
