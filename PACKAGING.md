# Packaging

How to build a native desktop binary of the Derivatives Underwriting Workbench.
This documents the build; **code signing and notarization are deliberately
deferred** and noted inline. The built artifact is still an educational tool
running on synthetic and public data.

## Prerequisites

```bash
pip install -e ".[build]"   # adds PyInstaller
```

The app depends on **PySide6 with QtWebEngine** (the charts and the memo preview
render in a `QWebEngineView`). QtWebEngine ships extra binaries and resources
that must be collected; the spec below does this by collecting all of PySide6.

## Build (both platforms)

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
  fully offline.

The bundle is large (~900 MB on Windows) because it includes the full Qt +
QtWebEngine runtime; trimming unused Qt modules is a future optimization.

### Verify the bundle

The app has a headless self-test that runs a full analysis (pipeline + plotly +
reportlab) and exits — use it to confirm every dependency is bundled, no display
required:

```bash
dist/DerivativesUnderwritingWorkbench/DerivativesUnderwritingWorkbench --selftest
# -> self-test OK (v1.0.0): peak PFE ..., recommendation ..., PDF ok
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

## Reproducibility

Every underwriting run saves its full `RunConfig` (including the Monte Carlo
seed), and saved deals store their inputs — so a packaged build produces the same
numbers as running from source for the same seed. The app can check for newer
releases under **Settings → Preferences → Updates** and **Help → Check for
Updates**.
