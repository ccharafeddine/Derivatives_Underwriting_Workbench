# PyInstaller spec for the Derivatives Underwriting Workbench.
# Build with:  pyinstaller duw.spec   (see PACKAGING.md)
#
# Produces a one-folder bundle in dist/DerivativesUnderwritingWorkbench/. The
# whole of PySide6 is collected so QtWebEngine (used by the charts and the memo
# preview) ships with its process, resources, and locales; plotly is collected
# for its inlined plotly.js; and the synthetic market data is bundled so the app
# runs fully offline.

from PyInstaller.utils.hooks import collect_all, collect_data_files

datas = []
binaries = []
hiddenimports = []

for package in ("PySide6", "plotly"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# Bundle the synthetic market snapshot and seed counterparties.
datas += collect_data_files("duw", includes=["data/*.json"])

# reportlab / kaleido carry data files used by the report path.
datas += collect_data_files("reportlab")

a = Analysis(
    ["src/duw/app.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "ruff"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DerivativesUnderwritingWorkbench",
    debug=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="DerivativesUnderwritingWorkbench",
)
