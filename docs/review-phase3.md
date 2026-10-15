# Phase 3 expert review — Derivatives Underwriting Workbench

Scope: finance/risk math (EE/PFE, CVA/DVA/FVA, netting, collateral/MPoR, WWR,
curves), data validation, edge cases, performance and UX.

## Fixed on `phase3-review`

| # | Area | Finding | Fix |
|---|------|---------|-----|
| 1 | Collateral / MPoR | The lagged portfolio value V(t−MPoR) was linearly interpolated between grid dates. That throws away the diffusion variance inside the margin period, so collateralised PFE depended on the grid: peak PFE was 35k, 86k and 115k at 12, 60 and 126 steps. | The lag is now sampled with a Brownian bridge (reproducible seed), which keeps the gap variance at any grid. Peak PFE is now 90k, 108k and 115k. Lags that land exactly on a grid date are still exact. Tests are in `test_review_fixes.py`. |
| 2 | Campaign scoring | Fix 1 makes collateralised exposure realistically larger, which moved the `rising_rates_default` stage threshold. | The stage is recalibrated (`pass_ratio=0.65`) with a comment explaining why. |
| 3 | Data validation | `Trade` objects accepted non-finite or negative notionals, maturity on or before the trade date, negative spreads or vols, and CDS recovery ≥ 1 (which divides by zero in hazard bootstrapping). Bad JSON or scenario files failed deep inside the engine. | `Trade.__post_init__` now validates these with clear `Trade <id>: …` errors. The Trade page shows them inline instead of raising. |
| 4 | Memo PDF/PPTX | Charts were exported in the dark or graphite on-screen palette, which is unreadable on white paper. | A new `print` chart theme (white paper, ink-safe role colours) is used for memo figures. PNGs render at 2× scale. |
| 5 | Small screens | Tall pages forced a very tall minimum window height. | Pages now sit in a frameless scroll area. Minimum height dropped to about 270 px. |
| 6 | Theming | Trade-page status messages used hard-coded colours. | They now use theme tokens. |

## Investigated

* **Jagged EE profile — genuine, not a bug.** The sample IRS pays fixed annually and floating quarterly. EE drops after each float coupon and jumps after the annual fixed payment. A uniform time grid samples this sawtooth irregularly, so the profile looks jagged. With matched frequencies the profile is smooth.

## Proposed (not built: large or opinionated)

1. **Cashflow-aware time grid.** Add grid points just before and after each payment date, so the EE/PFE peaks (including settlement-risk spikes) are captured, and the plot no longer aliases.
2. **First-to-default BCVA.** CVA and DVA currently use independent marginal default probabilities. Weighting each by the other party's survival would remove the double count.
3. **Asymmetric FVA.** Split it into FCA and FBA with separate borrowing and lending spreads. Today it uses one symmetric spread.
4. **Wrong-way risk on DVA/FVA.** The rank-tilt WWR model applies to CVA only.
5. **Collateralised limit utilisation.** Limits compare uncollateralised peak PFE with the limit. Also show collateralised utilisation for CSA counterparties.
6. **Two-way CSA.** Model posted collateral (our threshold and independent amount) and initial margin (SIMM-style), not just collateral received.
7. **Simulator page restructure.** Split it into Setup, Run and Review sections with a persistent results rail. The current long form mixes inputs and outputs.
8. **Narrow-window top bar.** The header chips set a minimum width of about 1340 px. Collapse the chips into a menu below about 1400 px.
