"""Derivatives Underwriting Workbench (``duw``).

An educational desktop analytics application that reconstructs the
counterparty-credit underwriting workflow for OTC derivatives. Given a proposed
interest rate, FX, or credit derivative trade, it quantifies the counterparty
exposure created, prices in the counterparty's credit risk, checks it against
limits, models collateral, and produces an underwriting memo.

This is a portfolio / educational project. It runs on synthetic and public data
only, executes no trades, and is not affiliated with any financial institution.
"""

# Single source for the release version. pyproject.toml reads this attribute
# (see [tool.setuptools.dynamic]) so the package metadata, the in-app update
# check, and the frozen binary all report the same number.
__version__ = "1.1.1"
