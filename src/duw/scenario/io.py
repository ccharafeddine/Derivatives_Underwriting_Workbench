"""Load and save scenarios to a human-authorable JSON file.

This is the on-disk format the future instructor mode authors and shares: a
single, readable JSON document describing a whole scripted scenario — its
counterparties and their credit trajectories, the market path, the deal stream,
and the default events. Every enum is stored by its string value and every date
as an ISO ``YYYY-MM-DD`` string, so the file can be hand-edited.

:func:`load_scenario` validates on the way in and raises a
:class:`ScenarioError` (bad path / malformed JSON) or
:class:`ScenarioValidationError` (well-formed JSON that violates the scenario
rules) with a clear message. Pure data; no Qt imports.
"""

from __future__ import annotations

import json
from datetime import date
from importlib import resources
from pathlib import Path
from typing import Any

from duw.domain.counterparty import Counterparty, Financials
from duw.domain.instruments import (
    CDS,
    IRS,
    CdsDirection,
    CrossCurrencyDirection,
    CrossCurrencySwap,
    DayCount,
    Frequency,
    FxDirection,
    FXForward,
    SwapDirection,
    Swaption,
    SwaptionDirection,
    Trade,
)
from duw.risk.scenarios import ScenarioSpec
from duw.scenario.model import (
    CreditState,
    DealArrival,
    Decision,
    DecisionAction,
    DefaultEvent,
    MarketRound,
    Scenario,
    ScenarioCounterparty,
    ScenarioMeta,
    SimSettings,
)

# Bumped only on a breaking change to the on-disk schema.
SCHEMA_VERSION = 1

SCENARIOS_DIR = "scenarios"


class ScenarioError(Exception):
    """A scenario file could not be read or parsed."""


class ScenarioValidationError(ScenarioError):
    """A parsed scenario violates the scenario rules."""


# ---------------------------------------------------------------------------
# Trade (de)serialization — polymorphic over the five supported products
# ---------------------------------------------------------------------------


def _trade_to_dict(trade: Trade) -> dict[str, Any]:
    base: dict[str, Any] = {
        "product": trade.product,
        "trade_id": trade.trade_id,
        "counterparty_id": trade.counterparty_id,
        "notional": trade.notional,
        "currency": trade.currency,
        "trade_date": trade.trade_date.isoformat(),
        "maturity_date": trade.maturity_date.isoformat(),
    }
    if isinstance(trade, IRS):
        base.update(
            fixed_rate=trade.fixed_rate,
            direction=trade.direction.value,
            fixed_frequency=trade.fixed_frequency.value,
            float_frequency=trade.float_frequency.value,
            fixed_day_count=trade.fixed_day_count.value,
            float_day_count=trade.float_day_count.value,
            float_index=trade.float_index,
            float_spread=trade.float_spread,
        )
    elif isinstance(trade, FXForward):
        base.update(
            base_currency=trade.base_currency,
            quote_currency=trade.quote_currency,
            contract_rate=trade.contract_rate,
            direction=trade.direction.value,
        )
    elif isinstance(trade, CDS):
        base.update(
            reference_entity=trade.reference_entity,
            direction=trade.direction.value,
            spread=trade.spread,
            premium_frequency=trade.premium_frequency.value,
            day_count=trade.day_count.value,
            recovery_rate=trade.recovery_rate,
        )
    elif isinstance(trade, Swaption):
        base.update(
            strike=trade.strike,
            direction=trade.direction.value,
            underlying_tenor_years=trade.underlying_tenor_years,
            volatility=trade.volatility,
            underlying_frequency=trade.underlying_frequency.value,
            bought=trade.bought,
        )
    elif isinstance(trade, CrossCurrencySwap):
        base.update(
            foreign_currency=trade.foreign_currency,
            foreign_notional=trade.foreign_notional,
            base_rate=trade.base_rate,
            foreign_rate=trade.foreign_rate,
            direction=trade.direction.value,
            frequency=trade.frequency.value,
            exchange_notional=trade.exchange_notional,
        )
    else:  # pragma: no cover - guarded by the supported-product set
        raise ScenarioError(f"cannot serialize unsupported product {trade.product!r}")
    return base


def _common_trade_kwargs(d: dict[str, Any]) -> dict[str, Any]:
    return {
        "trade_id": d["trade_id"],
        "counterparty_id": d["counterparty_id"],
        "notional": float(d["notional"]),
        "currency": d["currency"],
        "trade_date": date.fromisoformat(d["trade_date"]),
        "maturity_date": date.fromisoformat(d["maturity_date"]),
    }


def _trade_from_dict(d: dict[str, Any]) -> Trade:
    product = d.get("product")
    common = _common_trade_kwargs(d)
    if product == "IRS":
        return IRS(
            **common,
            fixed_rate=float(d["fixed_rate"]),
            direction=SwapDirection(d["direction"]),
            fixed_frequency=Frequency(d.get("fixed_frequency", "annual")),
            float_frequency=Frequency(d.get("float_frequency", "quarterly")),
            fixed_day_count=DayCount(d.get("fixed_day_count", "30/360")),
            float_day_count=DayCount(d.get("float_day_count", "act/360")),
            float_index=d.get("float_index", "SOFR"),
            float_spread=float(d.get("float_spread", 0.0)),
        )
    if product == "FXForward":
        return FXForward(
            **common,
            base_currency=d["base_currency"],
            quote_currency=d["quote_currency"],
            contract_rate=float(d["contract_rate"]),
            direction=FxDirection(d["direction"]),
        )
    if product == "CDS":
        return CDS(
            **common,
            reference_entity=d["reference_entity"],
            direction=CdsDirection(d["direction"]),
            spread=float(d["spread"]),
            premium_frequency=Frequency(d.get("premium_frequency", "quarterly")),
            day_count=DayCount(d.get("day_count", "act/360")),
            recovery_rate=float(d.get("recovery_rate", 0.4)),
        )
    if product == "Swaption":
        return Swaption(
            **common,
            strike=float(d["strike"]),
            direction=SwaptionDirection(d["direction"]),
            underlying_tenor_years=float(d["underlying_tenor_years"]),
            volatility=float(d.get("volatility", 0.20)),
            underlying_frequency=Frequency(d.get("underlying_frequency", "annual")),
            bought=bool(d.get("bought", True)),
        )
    if product == "CrossCurrencySwap":
        return CrossCurrencySwap(
            **common,
            foreign_currency=d["foreign_currency"],
            foreign_notional=float(d["foreign_notional"]),
            base_rate=float(d["base_rate"]),
            foreign_rate=float(d["foreign_rate"]),
            direction=CrossCurrencyDirection(d["direction"]),
            frequency=Frequency(d.get("frequency", "annual")),
            exchange_notional=bool(d.get("exchange_notional", True)),
        )
    raise ScenarioValidationError(f"unknown or missing trade product: {product!r}")


# ---------------------------------------------------------------------------
# Counterparty (de)serialization
# ---------------------------------------------------------------------------


def _financials_to_dict(fin: Financials) -> dict[str, Any]:
    return {
        "total_assets": fin.total_assets,
        "total_liabilities": fin.total_liabilities,
        "current_assets": fin.current_assets,
        "current_liabilities": fin.current_liabilities,
        "retained_earnings": fin.retained_earnings,
        "ebit": fin.ebit,
        "sales": fin.sales,
        "market_equity": fin.market_equity,
        "equity_volatility": fin.equity_volatility,
        "currency": fin.currency,
    }


def _counterparty_to_dict(cp: Counterparty) -> dict[str, Any]:
    out: dict[str, Any] = {
        "counterparty_id": cp.counterparty_id,
        "name": cp.name,
        "sector": cp.sector,
        "ticker": cp.ticker,
        "cds_issuer": cp.cds_issuer,
        "internal_rating": cp.internal_rating,
    }
    if cp.financials is not None:
        out["financials"] = _financials_to_dict(cp.financials)
    return out


def _counterparty_from_dict(d: dict[str, Any]) -> Counterparty:
    fin_raw = d.get("financials")
    financials = Financials(**fin_raw) if fin_raw is not None else None
    return Counterparty(
        counterparty_id=d["counterparty_id"],
        name=d["name"],
        sector=d["sector"],
        ticker=d.get("ticker"),
        financials=financials,
        cds_issuer=d.get("cds_issuer"),
        internal_rating=d.get("internal_rating"),
    )


# ---------------------------------------------------------------------------
# ScenarioSpec, settings, and the scenario structure
# ---------------------------------------------------------------------------


def _spec_to_dict(spec: ScenarioSpec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "rate_shift_bps": spec.rate_shift_bps,
        "steepen_bps": spec.steepen_bps,
        "fx_shock_pct": spec.fx_shock_pct,
        "spread_widen_pct": spec.spread_widen_pct,
    }


def _spec_from_dict(d: dict[str, Any]) -> ScenarioSpec:
    return ScenarioSpec(
        name=d.get("name", "Base"),
        rate_shift_bps=float(d.get("rate_shift_bps", 0.0)),
        steepen_bps=float(d.get("steepen_bps", 0.0)),
        fx_shock_pct=float(d.get("fx_shock_pct", 0.0)),
        spread_widen_pct=float(d.get("spread_widen_pct", 0.0)),
    )


def _settings_to_dict(s: SimSettings) -> dict[str, Any]:
    return {
        "seed": s.seed,
        "n_paths": s.n_paths,
        "n_steps": s.n_steps,
        "horizon": s.horizon,
        "lgd": s.lgd,
        "own_credit_spread": s.own_credit_spread,
        "own_recovery": s.own_recovery,
        "funding_spread": s.funding_spread,
        "wwr_correlation": s.wwr_correlation,
        "kappa_rate": s.kappa_rate,
        "kappa_credit": s.kappa_credit,
        "credit_vol": s.credit_vol,
    }


def _settings_from_dict(d: dict[str, Any] | None) -> SimSettings:
    if not d:
        return SimSettings()
    known = {f: d[f] for f in _settings_to_dict(SimSettings()) if f in d}
    return SimSettings(**known)


def scenario_to_dict(scenario: Scenario) -> dict[str, Any]:
    """Serialize a :class:`Scenario` to a JSON-ready dict."""
    m = scenario.meta
    return {
        "schema_version": SCHEMA_VERSION,
        "meta": {
            "title": m.title,
            "description": m.description,
            "n_rounds": m.n_rounds,
            "learning_objectives": list(m.learning_objectives),
        },
        "settings": _settings_to_dict(scenario.settings),
        "counterparties": [
            {
                "counterparty": _counterparty_to_dict(cp.counterparty),
                "recovery_rate": cp.recovery_rate,
                "credit_path": [
                    {
                        "round": cs.round,
                        "spread_multiplier": cs.spread_multiplier,
                        "internal_rating": cs.internal_rating,
                    }
                    for cs in cp.credit_path
                ],
            }
            for cp in scenario.counterparties
        ],
        "market_path": [
            {"round": mr.round, "spec": _spec_to_dict(mr.spec)}
            for mr in scenario.market_path
        ],
        "deal_stream": [
            {"round": d.round, "trade": _trade_to_dict(d.trade)}
            for d in scenario.deal_stream
        ],
        "defaults": [
            {"round": e.round, "counterparty_id": e.counterparty_id}
            for e in scenario.defaults
        ],
    }


def scenario_from_dict(raw: dict[str, Any]) -> Scenario:
    """Build a validated :class:`Scenario` from a parsed dict."""
    try:
        meta_raw = raw["meta"]
        meta = ScenarioMeta(
            title=meta_raw["title"],
            description=meta_raw["description"],
            n_rounds=int(meta_raw["n_rounds"]),
            learning_objectives=tuple(meta_raw.get("learning_objectives", ())),
        )
        counterparties = tuple(
            ScenarioCounterparty(
                counterparty=_counterparty_from_dict(cp_raw["counterparty"]),
                recovery_rate=float(cp_raw.get("recovery_rate", 0.4)),
                credit_path=tuple(
                    CreditState(
                        round=int(cs["round"]),
                        spread_multiplier=float(cs.get("spread_multiplier", 1.0)),
                        internal_rating=cs.get("internal_rating"),
                    )
                    for cs in cp_raw.get("credit_path", ())
                ),
            )
            for cp_raw in raw["counterparties"]
        )
        market_path = tuple(
            MarketRound(round=int(mr["round"]), spec=_spec_from_dict(mr["spec"]))
            for mr in raw.get("market_path", ())
        )
        deal_stream = tuple(
            DealArrival(round=int(d["round"]), trade=_trade_from_dict(d["trade"]))
            for d in raw.get("deal_stream", ())
        )
        defaults = tuple(
            DefaultEvent(round=int(e["round"]), counterparty_id=e["counterparty_id"])
            for e in raw.get("defaults", ())
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ScenarioValidationError(f"malformed scenario: {exc}") from exc

    scenario = Scenario(
        meta=meta,
        counterparties=counterparties,
        market_path=market_path,
        deal_stream=deal_stream,
        defaults=defaults,
        settings=_settings_from_dict(raw.get("settings")),
    )
    validate_scenario(scenario)
    return scenario


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_scenario(scenario: Scenario) -> None:
    """Raise :class:`ScenarioValidationError` if the scenario is inconsistent."""
    n = scenario.meta.n_rounds
    if n < 1:
        raise ScenarioValidationError(f"n_rounds must be >= 1, got {n}")
    if not scenario.counterparties:
        raise ScenarioValidationError("scenario has no counterparties")

    ids: set[str] = set()
    for cp in scenario.counterparties:
        if cp.counterparty_id in ids:
            raise ScenarioValidationError(
                f"duplicate counterparty id {cp.counterparty_id!r}"
            )
        ids.add(cp.counterparty_id)
        if not 0.0 <= cp.recovery_rate <= 1.0:
            raise ScenarioValidationError(
                f"{cp.counterparty_id}: recovery_rate must be in [0, 1], "
                f"got {cp.recovery_rate}"
            )
        for cs in cp.credit_path:
            _require_round(cs.round, n, f"credit state for {cp.counterparty_id}")

    for mr in scenario.market_path:
        _require_round(mr.round, n, "market_path entry")

    for d in scenario.deal_stream:
        _require_round(d.round, n, f"deal {d.trade_id}")
        if d.counterparty_id not in ids:
            raise ScenarioValidationError(
                f"deal {d.trade_id} references unknown counterparty "
                f"{d.counterparty_id!r}"
            )

    for e in scenario.defaults:
        _require_round(e.round, n, "default event")
        if e.counterparty_id not in ids:
            raise ScenarioValidationError(
                f"default event references unknown counterparty {e.counterparty_id!r}"
            )


def _require_round(round_index: int, n_rounds: int, what: str) -> None:
    if not 0 <= round_index < n_rounds:
        raise ScenarioValidationError(
            f"{what}: round {round_index} out of range [0, {n_rounds})"
        )


# ---------------------------------------------------------------------------
# File / resource IO
# ---------------------------------------------------------------------------


def save_scenario(scenario: Scenario, path: str | Path) -> Path:
    """Write ``scenario`` to ``path`` as indented, human-readable JSON."""
    validate_scenario(scenario)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(scenario_to_dict(scenario), indent=2) + "\n", encoding="utf-8"
    )
    return out


def load_scenario(path: str | Path) -> Scenario:
    """Load and validate a scenario from a JSON file."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ScenarioError(f"scenario file not found: {p}") from exc
    except OSError as exc:
        raise ScenarioError(f"could not read scenario file {p}: {exc}") from exc
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ScenarioError(f"invalid JSON in scenario file {p}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ScenarioValidationError(f"scenario file {p} must contain a JSON object")
    return scenario_from_dict(raw)


def load_bundled_scenario(name: str) -> Scenario:
    """Load a scenario shipped under ``duw/data/scenarios/``.

    ``name`` may be given with or without the ``.json`` suffix.
    """
    filename = name if name.endswith(".json") else f"{name}.json"
    resource = resources.files("duw.data").joinpath(SCENARIOS_DIR, filename)
    try:
        with resources.as_file(resource) as path:
            return load_scenario(path)
    except FileNotFoundError as exc:  # pragma: no cover - defensive
        raise ScenarioError(f"no bundled scenario named {name!r}") from exc


def decision_to_dict(decision: Decision) -> dict[str, Any]:
    """Serialize a :class:`Decision` (used by callers that persist decisions)."""
    return {
        "trade_id": decision.trade_id,
        "action": decision.action.value,
        "require_collateral": decision.require_collateral,
        "csa_threshold": decision.csa_threshold,
        "csa_mta": decision.csa_mta,
        "csa_initial_margin": decision.csa_initial_margin,
        "csa_mpor_days": decision.csa_mpor_days,
        "limit": decision.limit,
    }


def decision_from_dict(d: dict[str, Any]) -> Decision:
    """Rebuild a :class:`Decision` from a dict."""
    return Decision(
        trade_id=d["trade_id"],
        action=DecisionAction(d["action"]),
        require_collateral=bool(d.get("require_collateral", False)),
        csa_threshold=float(d.get("csa_threshold", 0.0)),
        csa_mta=float(d.get("csa_mta", 0.0)),
        csa_initial_margin=float(d.get("csa_initial_margin", 0.0)),
        csa_mpor_days=int(d.get("csa_mpor_days", 10)),
        limit=float(d.get("limit", 5_000_000.0)),
    )
