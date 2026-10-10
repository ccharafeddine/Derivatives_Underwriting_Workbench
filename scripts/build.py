#!/usr/bin/env python3
"""Reproducible desktop build.

Creates a clean virtual environment, installs the pinned dependencies in
``requirements-build.txt``, runs lint and tests, builds with PyInstaller via
``duw.spec``, and zips the one-folder bundle.

On Windows the archive is
``dist/DerivativesUnderwritingWorkbench-<version>-windows.zip``.
Pass ``--archive-label windows`` to force that name on any platform.
``scripts/build_windows.ps1`` does that.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist"
BUNDLE = DIST_DIR / "DerivativesUnderwritingWorkbench"


def _run(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.check_call(cmd, cwd=ROOT, env=env)


def _venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _zip_bundle(source: Path, dest: Path) -> None:
    if dest.exists():
        dest.unlink()
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source.parent).as_posix())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--venv",
        default=".venv-build",
        help="virtual environment directory, relative to the repo root",
    )
    parser.add_argument(
        "--archive-label",
        default="",
        help="zip suffix; default is 'windows' on Windows and sys.platform elsewhere",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="skip ruff and pytest (not for a release build)",
    )
    args = parser.parse_args(argv)

    venv = (ROOT / args.venv).resolve()
    if venv.exists():
        shutil.rmtree(venv)
    _run([sys.executable, "-m", "venv", str(venv)])
    py = str(_venv_python(venv))
    _run([py, "-m", "pip", "install", "--upgrade", "pip"])
    _run([py, "-m", "pip", "install", "-r", "requirements-build.txt"])
    _run([py, "-m", "pip", "install", "-e", ".", "--no-deps"])

    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QT_OPENGL"] = "software"
    env["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
    env["QTWEBENGINE_CHROMIUM_FLAGS"] = "--no-sandbox --disable-gpu"

    if not args.skip_tests:
        _run([py, "-m", "ruff", "check", "."], env=env)
        _run([py, "-m", "ruff", "format", "--check", "."], env=env)
        _run([py, "-m", "pytest", "-q"], env=env)

    _run([py, "-m", "PyInstaller", "duw.spec", "--noconfirm", "--clean"], env=env)
    if not BUNDLE.is_dir():
        print(f"PyInstaller did not produce {BUNDLE}", file=sys.stderr)
        return 1

    version = subprocess.check_output(
        [py, "-c", "import duw; print(duw.__version__, end='')"],
        cwd=ROOT,
        text=True,
    ).strip()
    if args.archive_label:
        label = args.archive_label
    elif sys.platform == "win32":
        label = "windows"
    else:
        label = sys.platform
    archive = DIST_DIR / f"DerivativesUnderwritingWorkbench-{version}-{label}.zip"
    _zip_bundle(BUNDLE, archive)
    print(f"Wrote {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
