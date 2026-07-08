# Packaging

How to build a native desktop binary of the Derivatives Underwriting Workbench.
This documents the build steps; **code signing and notarization are deliberately
deferred** and noted inline. Nothing here changes the app's honest framing: the
built artifact is still an educational tool running on synthetic and public data.

## Prerequisites

```bash
pip install -e ".[build]"   # adds PyInstaller
```

The app depends on **PySide6 with QtWebEngine** (used to render the plotly
charts and the memo preview). QtWebEngine ships extra binaries and resources that
PyInstaller must collect explicitly.

## One-folder build (both platforms)

```bash
pyinstaller \
  --name "DerivativesUnderwritingWorkbench" \
  --windowed \
  --collect-all PySide6 \
  --collect-all plotly \
  --collect-data kaleido \
  --collect-data duw \
  -p src \
  src/duw/app.py
```

Notes:

- `--collect-all PySide6` pulls in QtWebEngine's process and resources; without
  it the charts and memo preview render blank.
- `--collect-data duw` bundles the synthetic market snapshot and seed
  counterparties (`src/duw/data/*.json`) so the app runs fully offline.
- `--collect-data kaleido` is needed for static PNG chart export in the PDF memo.
- The result lands in `dist/DerivativesUnderwritingWorkbench/`.

Test the bundle before packaging an installer:

```bash
dist/DerivativesUnderwritingWorkbench/DerivativesUnderwritingWorkbench
```

## Windows installer (`.msi`)

1. Build the one-folder bundle above.
2. Wrap it in an MSI. Two common options:
   - **WiX Toolset** — author a `Product.wxs` referencing `dist/…` and run
     `candle` + `light`.
   - **`briefcase`** (BeeWare) — `briefcase create windows` / `briefcase build`
     / `briefcase package windows` produces a signed-capable MSI.
3. **Signing (deferred):** sign with `signtool sign /fd SHA256 /a` using an
   Authenticode certificate. Not wired here; the unsigned MSI will raise a
   SmartScreen prompt on first run.

## macOS app bundle and `.dmg`

1. Build with `--windowed` to get `dist/DerivativesUnderwritingWorkbench.app`.
2. Create the disk image:
   ```bash
   create-dmg \
     --volname "Derivatives Underwriting Workbench" \
     "DerivativesUnderwritingWorkbench.dmg" \
     "dist/DerivativesUnderwritingWorkbench.app"
   ```
3. **Signing / notarization (deferred):** `codesign --deep --force --sign
   "Developer ID Application: …"` then `xcrun notarytool submit`. Not wired here;
   an unsigned `.app` requires right-click → Open on first launch.

## Reproducibility

Every underwriting run saves its full `RunConfig` (including the Monte Carlo
seed) as JSON, and saved deals store their inputs — so a packaged build produces
the same numbers as running from source for the same seed.
