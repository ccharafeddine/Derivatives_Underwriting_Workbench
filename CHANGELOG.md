# Changelog

## 1.1.1

- Merton fallback asset value is equity plus discounted debt, matching the structural model.
- CVA and DVA average exposure over each time interval instead of using only the end of the interval.
- The memo, CVA commentary, and FVA glossary state that FVA uses one funding spread applied symmetrically to net exposure.
- Mixed-currency netting sets are converted into the reporting currency at the simulated FX spot, or rejected with an error the analysis dialog can show.
- The CSA FX haircut applies only when the collateral currency differs from the netting-set currency.
- Collateral commentary and the memo state that the CSA model is one-way.
- yfinance, kaleido, and pyarrow moved to optional extras (`live`, `export`); a missing extra produces an install hint instead of a hard failure.
- Exposure reprice caches discount and survival curves and builds shifted discount curves with the same discount factors as before.
- Version 1.1.1 is single-sourced from `duw.__version__`. The update check compares version numbers, not strings.
- Reproducible build pins in `requirements-build.txt`, with `scripts/build.py` and `scripts/build_windows.ps1`.

## 1.1.0

- Campaign simulator, wrong-way risk, FVA, swaptions, and cross-currency swaps, as previously released.
