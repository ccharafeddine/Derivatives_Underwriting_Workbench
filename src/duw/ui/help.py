"""Plain-English help text for an entry-level underwriter.

These are the learning tooltips shown across the app (gated by the Settings menu
toggle, see :mod:`duw.ui.tooltips`). They explain *what a step or control is for*
in the workflow, aimed at someone fresh out of a finance master's who knows the
theory but not yet the desk process. They complement :mod:`duw.glossary`, which
defines the individual metrics that appear in the result tables.

Keep them short, concrete, and jargon-light; where a term is unavoidable, say
what it means in the same breath.
"""

from __future__ import annotations

# Per-tab help. The tabs are grouped by role — the three inputs you review, then
# the analytics, then the outputs — not numbered by the internal computation
# order (which differs; see the Market note). Framing them by group keeps the
# left-to-right reading consistent.
TAB_HELP: dict[str, str] = {
    "Trade": (
        "Input 1 of 3 — the deal itself. Describe the trade the client wants to do "
        "(product, size, rate, maturity, which side you're on). Everything "
        "downstream is measured against this trade. Start here."
    ),
    "Counterparty": (
        "Input 2 of 3 — who you'd be facing. Enter the client's financials and "
        "rating. The app estimates how likely they are to default (their PD), "
        "because the whole question is what happens if they fail while owing you."
    ),
    "Market": (
        "Input 3 of 3 — the market backdrop: the interest-rate curve, FX rates, "
        "credit spreads, and vols everything is priced against (bundled synthetic "
        "data you can inspect). It's third because you define your trade and "
        "counterparty first, then review the market they sit in. Note: inside the "
        "calculation engine the market loads first (pricing needs it), so you may "
        "see it called 'step 0' — but on screen it belongs with the inputs."
    ),
    "Exposure": (
        "Analytics — how much you could lose. Simulates thousands of future market "
        "paths, reprices the trade on each, and shows the exposure profile: the "
        "expected exposure (EE) and the bad-case potential future exposure (PFE)."
    ),
    "Limits": (
        "Analytics — does it fit? Every counterparty has a credit limit. This "
        "checks whether the new trade's peak exposure fits under that limit and how "
        "much room (headroom) is left. A trade that breaches the limit is flagged."
    ),
    "Collateral": (
        "Analytics — does collateral help? If the client posts collateral under a "
        "CSA agreement, your exposure to them shrinks. This shows the exposure with "
        "and without collateral, side by side, so you see how much it removes."
    ),
    "CVA": (
        "Analytics — the price of their default risk. CVA is the market value of "
        "the chance the counterparty defaults while owing you money; you charge it "
        "to the client. Built from the exposure profile and their default "
        "probability. Shows CVA (and DVA/FVA) and where it comes from over time."
    ),
    "Scenario": (
        "Analytics (stress test) — what if the market moves against you? Re-runs "
        "the exposure under a shocked market (rates jump, spreads blow out, FX "
        "moves) so you can see how bad the exposure could get in a rough market."
    ),
    "Sensitivities": (
        "Analytics — what moves the number? Shows how the exposure and CVA change "
        "when the market moves a little (a 1bp rate move, a 1bp spread move, an FX "
        "move), so you can see which risks the trade is really exposed to."
    ),
    "Memo": (
        "Output — the write-up. Assembles everything into an underwriting memo with "
        "a plain-English recommendation (approve / approve with conditions / "
        "decline) that you could hand to a credit committee. Exportable to PDF."
    ),
    "Pipeline": (
        "Output — your saved deals. Each analysis you run can be saved and reopened "
        "here, so you can track a pipeline of proposed trades and revisit numbers."
    ),
    "Simulator": (
        "Practice — learn by playing. A round-by-round role-play: deals arrive, you "
        "set collateral and limits and decide, then time advances and some "
        "counterparties default. You're scored on risk-adjusted P&L. A great place "
        "to start to get a feel for the whole job."
    ),
}


# Per-control help — what an individual input means and why it matters.
CONTROL_HELP: dict[str, str] = {
    # Trade
    "notional": (
        "The size of the trade, in the trade currency. Bigger notional means bigger "
        "exposure if the counterparty defaults. It scales almost everything else."
    ),
    "currency": "The currency the trade's cash flows and notional are denominated in.",
    "trade_date": "The day the trade starts. Exposure is measured from here forward.",
    "maturity_date": (
        "The day the trade ends. A longer life means more time for the market to "
        "move against you, so generally more potential future exposure."
    ),
    "fixed_rate": (
        "The fixed interest rate on the swap. A swap done at the current market "
        "(par) rate is worth roughly zero at inception; as rates move, it gains or "
        "loses value, which is what creates exposure."
    ),
    "direction": (
        "Which side you're on. 'Pay fixed' means you pay a fixed rate and receive "
        "the floating rate; you gain (and build exposure to the counterparty) when "
        "rates rise. 'Receive fixed' is the mirror image."
    ),
    "product": (
        "The kind of derivative: an interest-rate swap, FX forward, CDS, swaption, "
        "or cross-currency swap. Each has a different exposure behaviour."
    ),
    "strike": "The agreed rate/price the option can be exercised at.",
    "spread": "The annual premium on the CDS, in the quoted units.",
    "contract_rate": "The FX rate agreed today for exchange at maturity.",
    # Counterparty
    "cp_name": "The client / counterparty you'd be facing on this trade.",
    "cp_rating": (
        "The counterparty's credit rating (internal grade). Weaker ratings mean a "
        "higher probability of default, which raises the CVA you must charge."
    ),
    "cp_financials": (
        "Balance-sheet figures used to estimate default risk two ways: a Merton "
        "distance-to-default (from asset value and volatility) and an Altman "
        "Z-score. Both feed the probability of default."
    ),
    "cp_ticker": (
        "Optional public ticker. If set, the app can pull public financials "
        "(offline-safe; it falls back to the values you enter)."
    ),
    # Market
    "market_curve": (
        "The interest-rate (discount) curve from the market snapshot. It sets how "
        "future cash flows are valued and discounted to today."
    ),
    "market_vol": (
        "How much rates/FX are assumed to move. Higher volatility means a wider "
        "range of future outcomes, so higher potential future exposure."
    ),
    # Collateral (CSA)
    "csa_threshold": (
        "The unsecured amount: exposure below this level is not collateralized. A "
        "threshold of 0 means the counterparty covers essentially all of it; a high "
        "threshold means you carry more uncollateralized exposure."
    ),
    "csa_mta": (
        "Minimum Transfer Amount: collateral only changes hands once the amount due "
        "clears this size, to avoid moving trivial sums."
    ),
    "csa_im": (
        "Initial Margin: collateral posted up front, on top of mark-to-market, as "
        "an extra buffer against the gap at default."
    ),
    "csa_mpor": (
        "Margin Period of Risk: the number of business days it takes to close out "
        "and collect collateral after a default (e.g. 10). Exposure can still build "
        "during this gap, so a longer MPoR means collateral protects a bit less."
    ),
    "csa_fx_haircut": (
        "A discount applied to collateral posted in a different currency than the "
        "exposure, to buffer FX moves. 0 means single-currency collateral."
    ),
    # Limits
    "limit": (
        "The most peak exposure you're willing to carry to this counterparty. If "
        "the trade's peak PFE goes over it, that's a breach — a reason to shrink the "
        "trade, demand collateral, or decline."
    ),
    # Settings / model
    "lgd": (
        "Loss Given Default: the fraction you actually lose if the counterparty "
        "defaults, after recovery. 0.6 means you recover 40 cents on the dollar."
    ),
    "funding_bps": (
        "Your funding spread, in basis points, used for FVA — the cost of funding "
        "the uncollateralized exposure over the trade's life."
    ),
    "wwr": (
        "Wrong-way risk correlation. Above 0, exposure tends to rise exactly as the "
        "counterparty's credit worsens (the dangerous case), which raises CVA. 0 "
        "assumes exposure and default are independent."
    ),
    "mc_paths": (
        "How many random future market paths to simulate. More paths give smoother, "
        "more stable exposure numbers but take longer to compute."
    ),
    "mc_steps": (
        "How many time points along the trade's life the exposure is measured at."
    ),
    "mc_seed": (
        "The random seed. Fixing it makes every run reproducible — the same inputs "
        "always give the same numbers, which is what lets you isolate one change."
    ),
    # Simulator
    "sim_action": (
        "Your call on this deal: Approve it, approve it only with collateral "
        "(Condition), or Decline. Approving takes the exposure onto your book."
    ),
    "sim_collateral": (
        "Tick to require the counterparty to post collateral (a CSA). On a name that "
        "might default, this is what turns a closeout loss into zero."
    ),
    "sim_limit": (
        "The credit limit you set for this counterparty. Utilization and any breach "
        "are measured against it."
    ),
}


def tab_help(label: str) -> str:
    """Return the learning tooltip for a workflow tab, or an empty string."""
    return TAB_HELP.get(label, "")


def control_help(slug: str) -> str:
    """Return the learning tooltip for a control, or an empty string."""
    return CONTROL_HELP.get(slug, "")
