# Packaging

How to build a native desktop binary of the Derivatives Underwriting Workbench.
This documents the build; **code signing and notarization are deliberately
deferred** and noted inline. The built artifact is still an educational tool
running on synthetic and public data.

## Version

The release version is the string `__version__` in `src/duw/__init__.py`.
`pyproject.toml` reads that attribute (`[tool.setuptools.dynamic]`), and the
in-app update check compares it numerically to the latest GitHub release tag
(`1.10.0` is newer than `1.9.0`; a `v` prefix and a pre-release suffix are
ignored). This release is **1.1.1**.

## Prerequisites

Python 3.12 for the pinned build. `requirements-build.txt` records the
versions that installed cleanly and passed the test suite on 3.12; current
numpy and scipy releases in that file require 3.12. A source install on 3.11
still uses the ranges in `pyproject.toml` (that is what CI runs). The
reproducible build does not use whatever happens to be installed: it creates
a clean virtual environment and installs
[`requirements-build.txt`](requirements-build.txt) (exact pins, including
PyInstaller and the optional `live` and `export` extras so the frozen app can
fetch public financials and embed chart images).

Core installs (`pip install -e ".[dev]"`) do not need yfinance, kaleido, or
pyarrow. Without them the app still runs:

- **Fetch** on the counterparty tab says to install `duw[live]`.
- PDF and PPTX memos omit static chart images and say to install `duw[export]`.
  The HTML memo keeps its interactive plotly charts either way.

The app depends on **PySide6 with QtWebEngine** (the charts and the memo preview
render in a `QWebEngineView`). QtWebEngine ships extra binaries and resources
that must be collected; the spec below does this by collecting all of PySide6.

## Reproducible build

From the repository root.

Windows (produces `dist/DerivativesUnderwritingWorkbench-<version>-windows.zip`):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1
```

Any platform (same steps; the zip is named `...-windows.zip` on Windows and
`...-<platform>.zip` elsewhere):

```bash
python scripts/build.py
```

Both scripts:

1. Delete and recreate `.venv-build`.
2. Install the exact pins in `requirements-build.txt`.
3. Install this tree with `pip install -e . --no-deps` so the version comes
   from source.
4. Run `ruff check`, `ruff format --check`, and `pytest` headless
   (`QT_QPA_PLATFORM=offscreen`).
5. Run `pyinstaller duw.spec --noconfirm --clean`.
6. Zip `dist/DerivativesUnderwritingWorkbench/` to
   `dist/DerivativesUnderwritingWorkbench-<version>-windows.zip` on Windows.

`duw.spec` collects PySide6, plotly, reportlab, the bundled JSON market data,
and — when those packages are installed, as they are in the pinned build —
yfinance and kaleido. pyarrow is pinned for the `export` extra but is not
imported and is not bundled.

To refresh the pin file after a deliberate dependency change, install
`".[dev,build,live,export]"` into a clean environment, run the tests, and
replace `requirements-build.txt` with `pip freeze` (drop the editable `duw`
line). Do not edit pins by hand.

## Build (manual, both platforms)

A [`duw.spec`](duw.spec) drives the build:

```bash
pyinstaller duw.spec --noconfirm
```

This produces a one-folder bundle in
`dist/DerivativesUnderwritingWorkbench/`. The spec:

- collects **all of PySide6** so QtWebEngine's process, resources, and locales
  ship (without this the charts and memo preview render blank),
- collects **plotly** for its inlined plotly.js (offline charts),
- bundles the **synthetic market data** (`src/duw/data/*.json`) so the app runs
  fully offline,
- collects **yfinance** and **kaleido** when they are installed, because those
  imports are lazy.

The bundle is large (~900 MB on Windows) because it includes the full Qt +
QtWebEngine runtime; trimming unused Qt modules is a future optimization.

### Verify the bundle

The app has a headless self-test that runs a full analysis (pipeline + plotly +
reportlab) and exits — use it to confirm every dependency is bundled, no display
required:

```bash
dist/DerivativesUnderwritingWorkbench/DerivativesUnderwritingWorkbench --selftest
# -> self-test OK (v1.1.1): peak PFE ..., recommendation ..., PDF ok
```

Then launch the GUI to confirm QtWebEngine renders:

```bash
dist/DerivativesUnderwritingWorkbench/DerivativesUnderwritingWorkbench
```

## Windows installer (`.msi`)

1. Build the one-folder bundle above.
2. Wrap it in an MSI. Two common options:
   - **WiX Toolset** — author a `Product.wxs` referencing `dist/…` and run
     `candle` + `light`.
   - **`briefcase`** (BeeWare) — `briefcase package windows` produces an MSI.
3. **Signing (deferred):** sign with `signtool sign /fd SHA256 /a` using an
   Authenticode certificate. Unsigned, the MSI raises a SmartScreen prompt on
   first run.

## macOS app bundle and `.dmg`

1. Build with the spec to get `dist/DerivativesUnderwritingWorkbench.app`.
2. Create the disk image:
   ```bash
   create-dmg \
     --volname "Derivatives Underwriting Workbench" \
     "DerivativesUnderwritingWorkbench.dmg" \
     "dist/DerivativesUnderwritingWorkbench.app"
   ```
3. **Signing / notarization (deferred):** `codesign --deep --force --sign
   "Developer ID Application: …"` then `xcrun notarytool submit`. Unsigned, the
   `.app` requires right-click → Open on first launch.

## Run reproducibility

Every underwriting run keeps its full `RunConfig` (including the Monte Carlo
seed), and saved deals store their inputs — so a packaged build produces the same
numbers as running from source for the same seed. The app can check for newer
releases under **Settings → Preferences → Updates** and **Help → Check for
Updates**. The check compares version tuples numerically.
