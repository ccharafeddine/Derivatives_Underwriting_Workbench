# Build plan — Claude Code sessions

Sequenced, paste-ready prompts for building the Derivatives Underwriting
Workbench. Run one session at a time, in order. Each leaves the repo in a
working, tested state. Each prompt is self-contained; paste it as-is.

Before session 0, put `CLAUDE.md`, `README.md`, and this file in an otherwise
empty repo folder and initialize git.

Convention used in every prompt: **orient first (no code)**, then build a
bounded scope, respect the DO NOTs, and pass the verification gates before
finishing.

---

## Session 0 — Scaffold and app shell

```
Orient first, write no code yet: read CLAUDE.md and README.md in full, then list
the directory layout and pipeline you find there back to me in a few sentences so
I know we're aligned. Then proceed.

Goal: stand up the project skeleton and an empty app shell that launches.

Build:
- pyproject.toml targeting Python 3.11+, package `duw` under src/, with runtime
  deps (PySide6, numpy, pandas, scipy, plotly, kaleido, pyarrow, yfinance,
  reportlab, python-pptx) and a dev extra (ruff, pytest). Configure ruff and
  pytest here.
- The full package directory layout from CLAUDE.md as empty packages with
  __init__.py files and module stubs (docstring + TODO only) so the structure
  exists.
- config.py: an AppSettings wrapper over QSettings (org/app name, get/set with
  defaults).
- app.py: a QApplication entry point and a QMainWindow with a menu bar
  (File / Edit / View / Settings) and a QTabWidget holding eight empty placeholder
  tabs named Trade, Counterparty, Exposure, Limits, Collateral, CVA, Memo,
  Pipeline. `python -m duw.app` must launch and show the window.
- A tests/ package with one trivial passing test that imports duw.
- A short "commands" note in the README's getting-started section if anything
  differs from what's written.

Do NOT: implement any pricing, risk, credit, or UI logic beyond empty tabs. No
network calls. Do not deviate from the layout in CLAUDE.md.

Verify before finishing:
- `ruff check . && ruff format --check .` clean.
- `QT_QPA_PLATFORM=offscreen pytest -q` passes.
- Confirm `QT_QPA_PLATFORM=offscreen python -c "import duw.app"` imports without
  error, and describe that the window builds.
- Summarize what you changed and paste the gate output.
```

---

## Session 1 — Domain model and market data

```
Orient first, no code yet: read CLAUDE.md (esp. the domain glossary and modeling
approach) and the current domain/ and data/ stubs. Confirm the dataclasses you
intend to create and their fields back to me, then proceed.

Goal: define the domain model and a loadable bundled market snapshot.

Build in src/duw/domain/ and src/duw/data/:
- instruments.py: a Trade base plus IRS, FXForward, and CDS dataclasses with the
  economic terms each needs (notional, currency, tenor/maturity, direction,
  fixed/float terms, spread, etc.), and a NettingSet holding a counterparty id
  and a list of trades. Frozen dataclasses, full type hints, unit notes in
  docstrings.
- market.py: a MarketSnapshot dataclass holding one or more zero/discount curves
  by currency, FX spot rates, a simple flat or tenor-based vol per factor, and
  CDS spread curves by issuer. Include an as-of date.
- counterparty.py: Counterparty (id, name, sector, optional public ticker,
  financials needed for Altman and Merton) and a CreditProfile result stub.
- results.py: a mutable AnalysisResults aggregate plus frozen sub-result
  dataclasses for each pipeline step (fields can be filled in later sessions;
  define the containers now).
- A bundled synthetic snapshot in data/ (JSON or parquet) — a couple of currency
  curves, a few FX rates, and CDS spreads — plus a small set of synthetic seed
  counterparties in data/. A loader function that reads them into the dataclasses
  and works fully offline.

Do NOT: add pricing or simulation math yet. No Qt imports in domain/. No network
calls in the loader.

Verify: ruff clean; `QT_QPA_PLATFORM=offscreen pytest -q` passes with new tests
that construct each dataclass and load the bundled snapshot and counterparties.
Summarize and paste gate output.
```

---

## Session 2 — Curves and pricing models

```
Orient first, no code yet: read CLAUDE.md's modeling approach and the domain
model from domain/instruments.py and domain/market.py. Confirm the pricing
signatures you'll implement, then proceed.

Goal: analytic, curve-based pricers for IRS, FX forward, and CDS.

Build in src/duw/pricing/:
- curves.py: a discount curve built from the snapshot's zeros with log-linear
  interpolation on discount factors; forward-rate extraction; and a survival
  curve bootstrapped from CDS spreads with a piecewise-constant hazard rate
  (given a recovery/LGD assumption).
- irs.py: price an interest rate swap as PV(fixed) vs PV(float) off the curve,
  returning MtM to us given direction. Support pricing at a future date under a
  shifted curve (needed later for exposure).
- fx_forward.py: price an FX forward via covered interest parity; MtM =
  discounted (contracted forward - prevailing forward) x notional.
- cds.py: price a CDS as PV(protection leg) - PV(premium leg) using the survival
  and discount curves, returning MtM given protection buyer/seller direction.
- Each pricer takes a market state (curves/FX/survival) plus a valuation date, so
  it can be called both at inception and along a simulated path.

Do NOT: add Monte Carlo or exposure logic yet. No Qt. Keep pricers pure.

Verify: ruff clean; pytest passes with tests asserting sensible behavior — a par
IRS is ~0 MtM at inception; an FX forward struck at the market forward is ~0; CDS
MtM signs are correct for buyer vs seller; discount factors are monotone in
tenor. Summarize and paste gate output.
```

---

## Session 3 — Risk-factor simulation and exposure engine

```
Orient first, no code yet: read CLAUDE.md's modeling and glossary sections and
the pricers in pricing/. Confirm your simulation and exposure design (processes,
grid, metrics) back to me, then proceed.

Goal: Monte Carlo exposure — the core engine producing EE/EPE/PFE.

Build in src/duw/risk/:
- simulators.py: seeded risk-factor simulators — a Hull-White one-factor short
  rate calibrated to the initial curve (a Vasicek approximation is an acceptable
  fallback; note it in the docstring if used), GBM for FX spot with drift = rate
  differential, and a mean-reverting process for the credit spread. All take an
  explicit rng/seed and a time grid; no global random state.
- exposure.py: an ExposureEngine that, given a netting set, a market snapshot,
  the relevant simulator(s), a time grid, and a path count, reprices the netting
  set on every path at every date to build a net MtM cube, takes the positive
  part, and returns an exposure profile: EE(t), EPE, PFE(t) at 95% and 99%, peak
  PFE, and the percentile cone. Populate the exposure sub-result in results.py.

Do NOT: add collateral, CVA, or limits yet. No Qt. Keep it pure and headless.

Verify: ruff clean; pytest passes with tests asserting exposure is non-negative,
PFE(99) >= PFE(95) >= EE at each date, results are reproducible for a fixed seed,
and a rough Monte Carlo convergence check (mean stabilizes as paths increase).
Summarize and paste gate output.
```

---

## Session 4 — Counterparty credit assessment

```
Orient first, no code yet: read CLAUDE.md's credit modeling notes and
domain/counterparty.py. Confirm the Merton solve and rating map you'll implement,
then proceed.

Goal: assess counterparty creditworthiness into a rating and PD term structure.

Build in src/duw/credit/:
- merton.py: a KMV-style Merton model that solves for asset value and asset vol
  from equity value, equity vol, and debt, then computes distance-to-default and
  PD = N(-DtD). Handle the numerical solve robustly with sane fallbacks.
- altman.py: the Altman Z-score from the counterparty's financial ratios, with
  the standard coefficients and the distress/grey/safe zones.
- rating.py: map a PD to an internal rating grade via a lookup table, and build a
  PD term structure for the counterparty — from its CDS spread curve if present,
  otherwise scaled from the Merton PD or the rating. Populate the CreditProfile
  result.
- Optionally, a helper that pulls a public counterparty's financials via
  yfinance to feed Merton/Altman — wrapped in try/except, validating the ticker
  resolves to the intended issuer, and always degrading to synthetic data.

Do NOT: wire this into the pipeline or UI yet. No Qt. yfinance must be optional
and non-fatal.

Verify: ruff clean; pytest passes with tests on Merton (higher leverage/vol -> higher
PD), Altman zones, PD-to-grade mapping, and a monotone, sensible PD term
structure. Tests must not require network access. Summarize and paste gate output.
```

---

## Session 5 — CVA/DVA and collateral (CSA)

```
Orient first, no code yet: read CLAUDE.md's CVA and CSA glossary/modeling notes,
the exposure engine in risk/exposure.py, and the survival curve in
pricing/curves.py. Confirm your CVA formula and collateral model, then proceed.

Goal: price counterparty credit risk and model collateral mitigation.

Build in src/duw/risk/:
- cva.py: unilateral CVA from the EE profile, the counterparty survival curve,
  marginal default probabilities per interval, LGD, and discounting; the
  symmetric DVA from own credit; and BCVA = CVA - DVA. Populate the CVA
  sub-result.
- collateral.py: apply a CSA (threshold, MTA, initial margin, margin period of
  risk) to the net exposure using a simplified MPoR model — collateralized
  exposure is exposure above the threshold accrued over the MPoR window, reduced
  by initial margin. Return collateralized EE/PFE alongside the uncollateralized
  profile so they can be compared.

Do NOT: implement wrong-way risk, funding/other XVA, or multi-currency
collateral. Leave a clear hook for wrong-way risk but do not build it. No Qt.

Verify: ruff clean; pytest passes with tests showing CVA rises with PD and with
exposure; DVA behaves symmetrically; a tighter CSA (lower threshold, more IM)
reduces collateralized exposure and CVA versus uncollateralized. Summarize and
paste gate output.
```

---

## Session 6 — Limits and netting check

```
Orient first, no code yet: read CLAUDE.md's limits notes, the exposure engine,
and the NettingSet model. Confirm how you'll compute incremental exposure, then
proceed.

Goal: check a proposed trade against a counterparty credit limit.

Build in src/duw/risk/limits.py:
- A per-counterparty PFE-based limit and a check that computes: current
  netting-set peak PFE, utilization vs the limit, remaining headroom, the
  incremental peak PFE the proposed trade adds (PFE with the new trade minus PFE
  of the existing set), and a breach flag when utilization would exceed 100%.
- Populate the limit-check sub-result. Handle an empty existing set (the proposed
  trade is the whole set).

Do NOT: add UI or pipeline wiring yet. No Qt.

Verify: ruff clean; pytest passes with tests: incremental exposure of a trade
added to an empty set equals its standalone PFE; a trade that pushes past the
limit flags a breach; headroom + utilization reconcile to the limit. Summarize
and paste gate output.
```

---

## Session 7 — Pipeline orchestrator and background worker

```
Orient first, no code yet: read CLAUDE.md's pipeline section and every module in
pricing/, risk/, and credit/. Confirm the step order and the AnalysisResults flow,
then proceed.

Goal: wire the twelve pipeline steps into one orchestrated, reproducible run,
runnable off-thread.

Build in src/duw/pipeline/:
- orchestrator.py: a function/class that runs steps 0-9 in order (load snapshot,
  build trade + netting set, assess credit, simulate, reprice, aggregate,
  exposure, collateral, CVA, limits), threading a single AnalysisResults through,
  taking a run config that includes the Monte Carlo seed. Steps 10-11 (memo,
  save) are stubbed for now with clear hooks. Emit a progress fraction + message
  per step via a simple callback.
- worker.py: a QThread worker wrapping the orchestrator, emitting progress and
  finished/error signals, so the UI never blocks. This is the only file here that
  imports Qt.
- Save the run config as JSON with the results for reproducibility.

Do NOT: build UI tabs yet. Keep the orchestrator itself Qt-free (Qt only in
worker.py).

Verify: ruff clean; pytest passes including a headless smoke test that runs the
full orchestrator on a seed trade end-to-end and asserts every step's sub-result
is populated and a fixed seed reproduces identical exposure numbers. Summarize
and paste gate output.
```

---

## Session 8 — UI: input tabs (Trade and Counterparty)

```
Orient first, no code yet: read CLAUDE.md's UI conventions, app.py, config.py,
and domain/instruments.py + domain/counterparty.py. Confirm the form layout and
how selections feed the run config, then proceed.

Goal: real Trade and Counterparty input tabs.

Build in src/duw/ui/tabs/:
- trade_tab.py: a term-sheet form that switches fields by product (IRS / FX
  forward / CDS), captures all economic terms, and validates input. It builds a
  Trade object and contributes to the run config.
- counterparty_tab.py: select a synthetic seed counterparty or enter one
  (optionally by public ticker), showing the financials that feed Merton/Altman.
- Use QSplitter where a form/summary split helps. Wire both tabs into the main
  window and a shared app state/run-config object. No analytics yet — just
  capture and validate inputs and enable a (not-yet-wired) Run action.

Do NOT: run the pipeline from the UI yet or build charts. Keep numeric modules
untouched.

Verify: ruff clean; `QT_QPA_PLATFORM=offscreen pytest -q` passes with offscreen
widget tests that instantiate each tab, set fields, and assert a valid Trade /
Counterparty is produced. Confirm the app still launches. Summarize and paste
gate output.
```

---

## Session 9 — UI: analytics tabs with plotly

```
Orient first, no code yet: read the exposure/collateral/cva/limits results in
results.py, the worker in pipeline/worker.py, and the input tabs. Confirm how the
Run action triggers the worker and how results reach the tabs, then proceed.

Goal: wire the Run action to the background worker and render results.

Build:
- A Run action (menu + button) that launches pipeline/worker.py off-thread with a
  progress bar, then dispatches results to the tabs.
- ui/widgets/: a reusable plotly-in-Qt view and a results-table widget.
- exposure_tab.py: the EE/EPE line, the PFE cone, and peak-PFE callouts.
- limits_tab.py: utilization, headroom, incremental exposure, and breach state.
- collateral_tab.py: collateralized vs uncollateralized exposure side by side
  with editable CSA inputs (threshold, MTA, IM, MPoR) that re-run.
- cva_tab.py: CVA / DVA / BCVA with a contribution breakdown.

Do NOT: change the numeric engines. Keep all heavy computation on the worker
thread. No memo/report generation yet.

Verify: ruff clean; offscreen pytest passes with tests that feed a canned
AnalysisResults into each tab and assert it renders without error; add/keep a
smoke test that runs the worker to completion headlessly. Confirm the app
launches and a run populates the tabs. Summarize and paste gate output.
```

---

## Session 10 — Interpretation engine, underwriting memo, and reports

```
Orient first, no code yet: read CLAUDE.md's honest-framing and reports notes,
results.py, and the reports/ stubs. Confirm the memo sections and export formats,
then proceed.

Goal: turn a completed run into a written underwriting memo with a recommendation.

Build in src/duw/reports/:
- interpreter.py: plain-English commentary functions per section (counterparty
  credit, exposure, collateral effect, CVA, limit impact) driven off
  AnalysisResults, in the style of a credit analyst summarizing terms.
- memo.py: assemble a one-page underwriting memo (trade summary, counterparty
  snapshot, exposure metrics, collateral effect, CVA, limit impact,
  recommendation) and export standalone HTML and a reportlab PDF, embedding the
  key charts via kaleido.
- deck.py: an optional python-pptx client summary deck.
- Wire step 10 (interpret + memo) and step 11 (save outputs) into the
  orchestrator, and add a Memo tab that previews the memo and offers HTML / PDF /
  PPTX export.
- Keep every disclaimer from CLAUDE.md/README in the memo output; the
  recommendation is illustrative, never presented as real credit advice.

Do NOT: overstate the tool in any generated text. No claims of being a real bank
system. Keep numeric engines untouched.

Verify: ruff clean; pytest passes with tests that generate a memo from a canned
run and assert the HTML and PDF files are produced and contain the required
sections and disclaimer. Summarize and paste gate output.
```

---

## Session 11 — Deal pipeline tracker and run persistence

```
Orient first, no code yet: read CLAUDE.md, the store/ stub, and how runs/config
are saved in the orchestrator. Confirm the persistence schema and stages, then
proceed.

Goal: track deals across approval stages and persist/reopen runs.

Build:
- store/deals.py: local persistence (SQLite or JSON on disk) for saved
  underwriting runs and their stage — Requested, Under review, Credit approved,
  Documented, Executed — with save/load/list/update-stage operations.
- pipeline_tab.py: a board showing saved deals by stage, letting the user move a
  deal between stages and reopen a saved run to repopulate the analytics tabs.
- Hook "save this run" into the Run flow.

Do NOT: add multi-user, cloud sync, or accounts — local only. Keep numeric
engines untouched.

Verify: ruff clean; offscreen pytest passes with tests for save/load round-trip,
stage transitions, and reopening a run. Confirm the app launches and a saved deal
appears on the board. Summarize and paste gate output.
```

---

## Session 12 — Theming, disclaimers, packaging, and final sweep

```
Orient first, no code yet: read CLAUDE.md and README.md in full and skim every
package to inventory what exists. Confirm the punch list you'll address, then
proceed.

Goal: polish to a shippable v1.

Build:
- A clean, professional theme (dark-first is fine) applied app-wide, and an
  About/Disclaimer dialog carrying the full disclaimer from the README.
- Consistent error handling and empty/loading states across tabs; graceful
  offline behavior when yfinance is unavailable.
- A settings surface (Monte Carlo paths, seed, default LGD, confidence levels)
  backed by AppSettings.
- Packaging config to build native binaries (document the .dmg / .msi build
  steps; wiring the actual signed build can be deferred and noted as such).
- Tidy the README to match the finished app; ensure getting-started commands are
  correct.

Do NOT: add new analytics or products. No scope creep — this session is polish
and packaging only.

Verify: run the full gate sweep — ruff clean, `QT_QPA_PLATFORM=offscreen pytest -q`
green, app launches, and a full run from Trade through Memo works end to end.
Summarize everything changed and paste the final gate output.
```

---

## After v1

Extension points deliberately deferred (each is a future scoped session):
wrong-way risk in exposure and CVA; additional products (cross-currency swaps,
swaptions, options); funding and other XVA terms; multi-currency collateral;
richer curve construction; and code-signed, auto-updating release builds.
