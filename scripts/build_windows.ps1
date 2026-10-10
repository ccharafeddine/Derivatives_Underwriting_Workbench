# Reproducible Windows build of the Derivatives Underwriting Workbench.
# Produces dist/DerivativesUnderwritingWorkbench-<version>-windows.zip.
#
# Steps (implemented once in scripts/build.py, invoked here with the Windows
# archive name so the two entry points cannot drift):
#   1. Create a clean .venv-build.
#   2. Install the pinned requirements-build.txt.
#   3. Install this tree with pip install -e . --no-deps.
#   4. Run ruff and pytest headless.
#   5. Run PyInstaller with duw.spec.
#   6. Zip the bundle as DerivativesUnderwritingWorkbench-<version>-windows.zip.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $Python) {
    Write-Error "python was not found on PATH."
}

& python (Join-Path $PSScriptRoot "build.py") --archive-label windows
exit $LASTEXITCODE
