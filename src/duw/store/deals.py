"""Deal-pipeline persistence.

Saves underwriting runs to local JSON on disk and tracks each through the
approval stages Requested -> Under review -> Credit approved -> Documented ->
Executed. A saved :class:`Deal` stores the run's *inputs* (counterparty, existing
trades, proposed trade, and the reproducible :class:`RunConfig`) plus a small
headline summary, so reopening a deal re-runs the pipeline deterministically
rather than persisting the full result cube.

Local only: no accounts, cloud sync, or multi-user support. No Qt.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from enum import Enum, StrEnum
from pathlib import Path
from typing import Any

from duw.domain.counterparty import Counterparty, Financials
from duw.domain.instruments import (
    CDS,
    IRS,
    CdsDirection,
    Frequency,
    FxDirection,
    FXForward,
    NettingSet,
    SwapDirection,
    Swaption,
    SwaptionDirection,
    Trade,
)
from duw.domain.results import AnalysisResults
from duw.pipeline.orchestrator import RunConfig


class DealStage(StrEnum):
    """Approval stage of a deal."""

    REQUESTED = "Requested"
    UNDER_REVIEW = "Under review"
    CREDIT_APPROVED = "Credit approved"
    DOCUMENTED = "Documented"
    EXECUTED = "Executed"


# Stages in workflow order (used by the board and stage transitions).
STAGES: tuple[DealStage, ...] = tuple(DealStage)


def default_deal_store_path() -> Path:
    """Default on-disk location for the deal store (local, per-user)."""
    return Path.home() / ".duw" / "deals.json"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Serialization of domain inputs
# --------------------------------------------------------------------------- #
def _encode(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


def trade_to_dict(trade: Trade) -> dict[str, Any]:
    """Serialize a trade to a JSON-friendly dict tagged with its product."""
    data = {k: _encode(v) for k, v in asdict(trade).items()}
    data["product"] = trade.product
    return data


def trade_from_dict(data: dict[str, Any]) -> Trade:
    """Reconstruct a trade from :func:`trade_to_dict` output."""
    d = dict(data)
    product = d.pop("product")
    d["trade_date"] = date.fromisoformat(d["trade_date"])
    d["maturity_date"] = date.fromisoformat(d["maturity_date"])
    if product == "IRS":
        d["direction"] = SwapDirection(d["direction"])
        d["fixed_frequency"] = Frequency(d["fixed_frequency"])
        d["float_frequency"] = Frequency(d["float_frequency"])
        return IRS(**d)
    if product == "FXForward":
        d["direction"] = FxDirection(d["direction"])
        return FXForward(**d)
    if product == "CDS":
        d["direction"] = CdsDirection(d["direction"])
        d["premium_frequency"] = Frequency(d["premium_frequency"])
        return CDS(**d)
    if product == "Swaption":
        d["direction"] = SwaptionDirection(d["direction"])
        d["underlying_frequency"] = Frequency(d["underlying_frequency"])
        return Swaption(**d)
    raise ValueError(f"unknown product {product!r}")


def counterparty_to_dict(cp: Counterparty) -> dict[str, Any]:
    """Serialize a counterparty (with nested financials) to a dict."""
    return asdict(cp)


def counterparty_from_dict(data: dict[str, Any]) -> Counterparty:
    """Reconstruct a counterparty from :func:`counterparty_to_dict` output."""
    d = dict(data)
    fin = d.get("financials")
    financials = Financials(**fin) if fin is not None else None
    return Counterparty(
        counterparty_id=d["counterparty_id"],
        name=d["name"],
        sector=d["sector"],
        ticker=d.get("ticker"),
        financials=financials,
        cds_issuer=d.get("cds_issuer"),
        internal_rating=d.get("internal_rating"),
    )


def _summary(results: AnalysisResults) -> dict[str, Any]:
    s: dict[str, Any] = {}
    if results.counterparty is not None:
        s["counterparty"] = results.counterparty.name
    if results.netting_set is not None and results.netting_set.trades:
        proposed = results.netting_set.trades[-1]
        s["product"] = proposed.product
        s["notional"] = proposed.notional
    if results.credit_profile is not None:
        s["grade"] = results.credit_profile.internal_grade
    if results.exposure is not None:
        s["peak_pfe"] = results.exposure.peak_pfe
    if results.cva is not None:
        s["cva"] = results.cva.cva
    if results.limits is not None:
        s["utilization"] = results.limits.utilization
        s["breach"] = results.limits.breach
    if results.memo is not None:
        s["recommendation"] = results.memo.recommendation
    return s


# --------------------------------------------------------------------------- #
# Deal record
# --------------------------------------------------------------------------- #
@dataclass
class Deal:
    """A saved underwriting run and its approval stage."""

    deal_id: str
    name: str
    stage: DealStage
    created_at: str
    updated_at: str
    counterparty: dict[str, Any]
    existing_trades: list[dict[str, Any]]
    proposed_trade: dict[str, Any]
    run_config: dict[str, Any]
    summary: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_results(
        cls,
        name: str,
        results: AnalysisResults,
        stage: DealStage = DealStage.REQUESTED,
        deal_id: str | None = None,
    ) -> Deal:
        """Build a deal from a completed run's results."""
        if results.counterparty is None or results.netting_set is None:
            raise ValueError("results must have a counterparty and netting set")
        trades = list(results.netting_set.trades)
        if not trades:
            raise ValueError("results netting set has no trades")
        proposed = trades[-1]
        existing = trades[:-1]
        now = _now_iso()
        return cls(
            deal_id=deal_id or uuid.uuid4().hex,
            name=name,
            stage=stage,
            created_at=now,
            updated_at=now,
            counterparty=counterparty_to_dict(results.counterparty),
            existing_trades=[trade_to_dict(t) for t in existing],
            proposed_trade=trade_to_dict(proposed),
            run_config=dict(results.run_config),
            summary=_summary(results),
        )

    def to_run_inputs(self) -> tuple[Counterparty, NettingSet, Trade, RunConfig]:
        """Reconstruct ``(counterparty, existing_set, proposed_trade, config)``."""
        counterparty = counterparty_from_dict(self.counterparty)
        existing = tuple(trade_from_dict(t) for t in self.existing_trades)
        existing_set = NettingSet(
            netting_set_id=f"NS-{counterparty.counterparty_id}",
            counterparty_id=counterparty.counterparty_id,
            trades=existing,
        )
        proposed = trade_from_dict(self.proposed_trade)
        cfg = dict(self.run_config)
        if "confidence_levels" in cfg and isinstance(cfg["confidence_levels"], list):
            cfg["confidence_levels"] = tuple(cfg["confidence_levels"])
        config = RunConfig(**cfg)
        return counterparty, existing_set, proposed, config

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["stage"] = self.stage.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Deal:
        d = dict(data)
        d["stage"] = DealStage(d["stage"])
        return cls(**d)


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #
class DealStore:
    """JSON-file-backed store for :class:`Deal` records."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        raw = self.path.read_text(encoding="utf-8").strip()
        return json.loads(raw) if raw else []

    def _write(self, records: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(records, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def save(self, deal: Deal) -> None:
        """Insert or update a deal by ``deal_id``."""
        records = self._read()
        deal.updated_at = _now_iso()
        for i, rec in enumerate(records):
            if rec["deal_id"] == deal.deal_id:
                records[i] = deal.to_dict()
                break
        else:
            records.append(deal.to_dict())
        self._write(records)

    def get(self, deal_id: str) -> Deal | None:
        """Return the deal with ``deal_id`` or ``None``."""
        for rec in self._read():
            if rec["deal_id"] == deal_id:
                return Deal.from_dict(rec)
        return None

    def list(self) -> list[Deal]:
        """Return all deals, most recently updated first."""
        deals = [Deal.from_dict(rec) for rec in self._read()]
        return sorted(deals, key=lambda d: d.updated_at, reverse=True)

    def update_stage(self, deal_id: str, stage: DealStage) -> Deal:
        """Move a deal to ``stage`` and persist."""
        deal = self.get(deal_id)
        if deal is None:
            raise KeyError(f"no deal with id {deal_id!r}")
        deal.stage = stage
        self.save(deal)
        return deal

    def delete(self, deal_id: str) -> None:
        """Remove a deal by id (no error if absent)."""
        records = [r for r in self._read() if r["deal_id"] != deal_id]
        self._write(records)
