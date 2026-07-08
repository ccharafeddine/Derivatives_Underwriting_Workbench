"""Plain-English glossary of the counterparty-credit terms the app reports.

Used both by the Help > Glossary dialog and to auto-attach tooltips to metric
labels, so the app is self-teaching for someone new to the workflow. Pure data;
no Qt. Definitions are educational and deliberately simplified.
"""

from __future__ import annotations

# Ordered longest-key-first is not required here; ``lookup`` handles precedence.
GLOSSARY: dict[str, str] = {
    "Peak PFE": (
        "The maximum potential future exposure over the trade's life — the "
        "headline number a credit limit is set against."
    ),
    "PFE": (
        "Potential Future Exposure: a high-percentile (e.g. 95% or 99%) of "
        "positive exposure at a future date — a 'bad but plausible' amount we "
        "could lose if the counterparty defaulted then."
    ),
    "EPE": (
        "Expected Positive Exposure: the time-average of expected exposure over "
        "the trade's life. A key input to CVA."
    ),
    "EE": (
        "Expected Exposure: the mean of positive net mark-to-market at a future "
        "date across the simulated paths."
    ),
    "Exposure": (
        "What we would lose if the counterparty defaulted now: the positive part "
        "of the net mark-to-market, max(MtM, 0)."
    ),
    "BCVA": "Bilateral CVA: CVA minus DVA — the net credit valuation adjustment.",
    "CVA": (
        "Credit Valuation Adjustment: the market value of the counterparty's "
        "default risk over the netting set, built from expected exposure, the "
        "survival curve, and discounting."
    ),
    "DVA": (
        "Debit Valuation Adjustment: the symmetric own-credit term — the value of "
        "our own possible default to us."
    ),
    "FVA": (
        "Funding Valuation Adjustment: the cost (or benefit) of funding the net "
        "uncollateralized exposure over the trade's life, at a funding spread."
    ),
    "Wrong-way": (
        "Wrong-way risk: exposure tending to rise as the counterparty's credit "
        "worsens (positive exposure-credit correlation), which raises CVA. "
        "Negative correlation is right-way risk and lowers it."
    ),
    "LGD": "Loss Given Default: the fraction lost on default, equal to 1 - recovery.",
    "Recovery": "The fraction of exposure expected to be recovered on default.",
    "Distance-to-default": (
        "Merton/KMV: how many standard deviations of asset value sit between the "
        "firm today and its default point. Higher is safer."
    ),
    "Merton": (
        "A structural credit model that treats equity as a call option on the "
        "firm's assets, yielding a distance-to-default and a default probability."
    ),
    "Altman": (
        "The Altman Z-score: a balance-sheet score classifying a firm as safe, "
        "grey, or distressed."
    ),
    "PD": "Probability of Default over a stated horizon.",
    "Netting set": (
        "Trades under one ISDA master agreement that net against each other, so "
        "exposure is measured on the net position, not trade by trade."
    ),
    "Incremental": (
        "The extra peak PFE the proposed trade adds to the existing book "
        "(with-the-trade minus without-the-trade)."
    ),
    "Utilization": "Peak PFE as a fraction of the credit limit (100% = at the limit).",
    "Headroom": "The credit limit minus the proposed peak PFE — the room remaining.",
    "CSA": (
        "Credit Support Annex: the collateral agreement. Its parameters are the "
        "threshold, MTA, initial margin, and margin period of risk."
    ),
    "Threshold": (
        "The unsecured amount under a CSA below which no collateral is called."
    ),
    "MTA": "Minimum Transfer Amount: collateral only moves once the amount clears it.",
    "Initial margin": (
        "Collateral posted up front, independent of mark-to-market, as an extra buffer."
    ),
    "MPoR": (
        "Margin Period of Risk: the gap (e.g. 10 business days) over which "
        "collateral cannot be re-called, during which exposure can still build."
    ),
}


def lookup(label: str) -> str | None:
    """Return the definition whose term best matches ``label``, or ``None``.

    Matches the longest glossary term that appears (case-insensitively) in the
    label, so ``"Peak PFE (95%)"`` matches ``"Peak PFE"`` rather than ``"PFE"``.
    """
    lowered = label.lower()
    best_key: str | None = None
    for key in GLOSSARY:
        if key.lower() in lowered and (best_key is None or len(key) > len(best_key)):
            best_key = key
    return GLOSSARY[best_key] if best_key is not None else None
