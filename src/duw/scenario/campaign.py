"""The underwriting campaign: an ordered curriculum over the bundled scenarios.

The simulator on its own is a scenario picker — a learner can start anywhere and
has no way to know what they have and have not understood. This module turns it
into a course with a spine: an ordered list of :class:`CampaignStage`\\ s, each
naming one bundled scenario and the single concept it exists to teach, gated so
the next stage opens only once the current one is cleared.

**Stage order is the teaching order**, and it follows the dependency chain the
project's design principles set out: read exposure before collateralizing it,
understand netting before calibrating a CSA against it, hold a limit before
learning what wrong-way risk does to the exposure inside it. Reordering the
stages therefore changes the pedagogy, not just the menu.

Clearing a stage is measured against the scenario's own best-play benchmark (see
:mod:`duw.scenario.coaching`): ``ratio`` is the learner's risk-adjusted score as
a fraction of the benchmark's, and a stage clears at its ``pass_ratio``. That
keeps the bar relative to what the scenario actually affords rather than an
absolute currency amount, so an easy book and a hard one are graded on the same
scale.

**Guided versus unaided is a property of what the stage is for**, not of how far
into the campaign it sits. A stage that introduces a mechanism the learner has
never seen — the opening walk-through, the CSA terms, the CDS, the funding and
own-credit legs, the sensitivity report — is authored as a tutorial: the coach
explains each number and recommends a decision, and the learner predicts before
the analytics are revealed. A stage that asks the learner to *apply* a mechanism
they already met is unaided, because being told the answer there would defeat
the exercise. That is why stage 7 drops the coach immediately after six coached
stages, and why the capstone is unaided however late it falls.

Pure and headless: no Qt, no I/O. Persistence of a :class:`CampaignProgress`
lives in :mod:`duw.store.progress`; the simulator UI reads the campaign from
here and the saved progress from there.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

#: Default fraction of the best-play benchmark needed to clear a stage. Set
#: below the "solid pass" band so a learner who understood the lesson but left
#: some spread on the table still progresses; mastery is shown by the medal.
DEFAULT_PASS_RATIO = 0.60


@dataclass(frozen=True)
class CampaignStage:
    """One stage of the campaign: a bundled scenario plus why it is here.

    ``scenario_name`` is the bundled file stem passed to
    :func:`~duw.scenario.io.load_bundled_scenario`. ``title`` is the short stage
    name shown in the stage list (the scenario carries its own longer title and
    learning objectives, which are not duplicated here). ``concept`` is the one
    thing this stage teaches, in plain English.
    """

    scenario_name: str
    title: str
    concept: str
    pass_ratio: float = DEFAULT_PASS_RATIO


@dataclass(frozen=True)
class Campaign:
    """An ordered sequence of stages forming the course."""

    stages: tuple[CampaignStage, ...]

    def __len__(self) -> int:
        return len(self.stages)

    def __iter__(self):  # noqa: ANN204 - a plain iterator over the stages
        return iter(self.stages)

    @property
    def names(self) -> tuple[str, ...]:
        """Scenario names in stage order."""
        return tuple(s.scenario_name for s in self.stages)

    def index_of(self, scenario_name: str) -> int:
        """Zero-based stage index of ``scenario_name``, or ``-1`` if absent."""
        for i, stage in enumerate(self.stages):
            if stage.scenario_name == scenario_name:
                return i
        return -1

    def stage(self, scenario_name: str) -> CampaignStage | None:
        """The stage for ``scenario_name``, or ``None`` if it is not in the campaign."""
        idx = self.index_of(scenario_name)
        return self.stages[idx] if idx >= 0 else None


# ---------------------------------------------------------------------------
# The curriculum
# ---------------------------------------------------------------------------

#: The bundled curriculum, in teaching order.
#:
#: Stages 1-6 build the core decision (read the exposure, price the credit,
#: collateralize what will default, leave healthy names open) with the coach
#: naming who is weak. Stage 7 removes that crutch and makes the learner read
#: the credit dossier themselves, which is the point the game stops being a
#: reflex. Stages 8-9 open up the constraints the earlier stages hold fixed:
#: netting and the committee's limit, then the CSA itself, which up to here has
#: been a switch rather than a set of negotiated terms. Stages 10-13 repeat the
#: whole decision across the other four products, so the learner sees that the
#: workflow, not the instrument, is the skill. Stages 14-16 then price and
#: report what the earlier stages only sized: the funding and own-credit legs,
#: wrong-way risk, and the sensitivities that say which risk factor an exposure
#: is actually running on. Stage 17 is the unaided capstone.
#:
#: The collateral-terms stage deliberately follows netting rather than preceding
#: it: calibrating a threshold against a netting set only means something once
#: the learner knows the exposure is measured on the net of one master
#: agreement. Likewise FVA and DVA come after every product, because both are
#: read off the *shape* of an exposure profile and the learner needs several
#: shapes in hand before that comparison lands.
CAMPAIGN = Campaign(
    stages=(
        CampaignStage(
            scenario_name="tutorial_intro",
            title="1. Your first two deals",
            concept=(
                "The whole loop, hand-held: read peak PFE, charge CVA, and choose "
                "whether the name needs collateral."
            ),
            pass_ratio=0.50,
        ),
        CampaignStage(
            scenario_name="steady_book",
            title="2. A book where nobody defaults",
            concept=(
                "Over-caution is its own way to lose: collateral you did not need "
                "concedes spread, and a declined deal earns nothing."
            ),
        ),
        CampaignStage(
            scenario_name="balanced_growth_clean",
            title="3. Growing a clean book",
            concept=(
                "Keep healthy names open across several rounds and let the "
                "risk-adjusted score reward the retained spread."
            ),
        ),
        CampaignStage(
            scenario_name="rising_rates_default",
            title="4. Rising rates, a name goes down",
            concept=(
                "A payer swap moves into the money as rates rise, growing the "
                "exposure on exactly the name whose credit is deteriorating."
            ),
        ),
        CampaignStage(
            scenario_name="rates_rally_default",
            title="5. The mirror: rates rally",
            concept=(
                "Direction decides who is exposed. A receiver swap gains as rates "
                "fall, so the same credit story needs the opposite read."
            ),
        ),
        CampaignStage(
            scenario_name="mixed_book_one_default",
            title="6. Three names, one fails",
            concept=(
                "Underwrite name by name from the credit evidence rather than "
                "applying one blanket policy across the book."
            ),
        ),
        CampaignStage(
            scenario_name="credit_evidence",
            title="7. Reading the dossier",
            concept=(
                "Nobody names the weak counterparties. Rank them yourself from "
                "distance-to-default, PD, Altman zone, and the CDS spread."
            ),
            pass_ratio=0.65,
        ),
        CampaignStage(
            scenario_name="netting_benefit",
            title="8. Netting and headroom",
            concept=(
                "Exposure is on the net MtM of one master agreement, and it is "
                "checked against a limit the committee sets, not you."
            ),
        ),
        CampaignStage(
            scenario_name="collateral_terms",
            title="9. Calibrating the CSA",
            concept=(
                "Collateral is a dial, not a switch: threshold, initial margin "
                "and the margin period of risk each decide how much you keep."
            ),
        ),
        CampaignStage(
            scenario_name="dollar_surge_fx",
            title="10. FX forwards",
            concept=(
                "The same workflow on an FX forward, where the exposure is driven "
                "by spot moving away from the contracted rate."
            ),
        ),
        CampaignStage(
            scenario_name="rate_vol_swaptions",
            title="11. Swaptions",
            concept=(
                "A bought option gives one-sided exposure: the premium is paid, "
                "and only the counterparty can owe you."
            ),
        ),
        CampaignStage(
            scenario_name="crossccy_funding_clean",
            title="12. Cross-currency swaps",
            concept=(
                "Two curves and an FX rate drive the exposure, so notional "
                "exchange makes the profile larger than a single-currency swap."
            ),
        ),
        CampaignStage(
            scenario_name="cds_protection",
            title="13. Credit default swaps",
            concept=(
                "A CDS holds two credits, and you underwrite only one: the "
                "counterparty who owes the payout, never the reference entity."
            ),
        ),
        CampaignStage(
            scenario_name="funding_and_own_credit",
            title="14. Funding and own credit",
            concept=(
                "FVA and DVA are priced off the shape of the profile, not its "
                "size — a one-way position is the most expensive kind to carry."
            ),
        ),
        CampaignStage(
            scenario_name="wrong_way_risk",
            title="15. Wrong-way risk",
            concept=(
                "When exposure rises precisely as the counterparty's credit "
                "worsens, independence understates the CVA you should charge."
            ),
            pass_ratio=0.55,
        ),
        CampaignStage(
            scenario_name="sensitivities_desk",
            title="16. Sensitivities",
            concept=(
                "DV01, CS01 and FX delta say which risk factor an exposure is "
                "actually running on, which the headline number never does."
            ),
        ),
        CampaignStage(
            scenario_name="credit_crunch_two_defaults",
            title="17. Capstone: the crunch",
            concept=(
                "Everything at once, unaided: several names, two of them failing, "
                "and no coach telling you which."
            ),
            # Deliberately the highest bar in the campaign. Two of this stage's
            # three names fail, so a learner who simply collateralizes everything
            # is accidentally right about most of the book and still reaches ~74%
            # of best play. Requiring 80% means the capstone can only be cleared
            # by getting the survivor right too — that is, by discriminating
            # rather than by blanket caution.
            pass_ratio=0.80,
        ),
    )
)


# ---------------------------------------------------------------------------
# Medals
# ---------------------------------------------------------------------------

#: Medal thresholds as fractions of the best-play benchmark, best first. These
#: mirror the bands in :func:`duw.scenario.coaching._band` so the stage list and
#: the end-of-run verdict never disagree about how well a run went.
MEDAL_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (0.95, "Gold"),
    (0.75, "Silver"),
    (0.45, "Bronze"),
)


def medal(ratio: float) -> str:
    """Medal for a score ``ratio`` against best play (``""`` when below bronze)."""
    for threshold, name in MEDAL_THRESHOLDS:
        if ratio >= threshold:
            return name
    return ""


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StageRecord:
    """What the learner has done on one stage.

    ``best_ratio`` and ``best_score`` are the learner's high-water marks across
    every attempt, so replaying a stage can only improve the record. ``cleared``
    latches: once a stage has been passed it stays passed, and a later weaker
    attempt does not re-lock the stages after it.
    """

    scenario_name: str
    plays: int = 0
    cleared: bool = False
    best_ratio: float = 0.0
    best_score: float = 0.0

    @property
    def medal(self) -> str:
        """Medal earned on the learner's best attempt at this stage."""
        return medal(self.best_ratio) if self.plays else ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_name": self.scenario_name,
            "plays": self.plays,
            "cleared": self.cleared,
            "best_ratio": self.best_ratio,
            "best_score": self.best_score,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StageRecord:
        return cls(
            scenario_name=str(data["scenario_name"]),
            plays=int(data.get("plays", 0)),
            cleared=bool(data.get("cleared", False)),
            best_ratio=float(data.get("best_ratio", 0.0)),
            best_score=float(data.get("best_score", 0.0)),
        )


@dataclass(frozen=True)
class CampaignProgress:
    """The learner's progress through the campaign.

    Immutable: :meth:`with_result` returns a new progress rather than mutating,
    which keeps the UI's "what changed" logic trivial and makes the object safe
    to hand to a background thread. ``practice_mode`` unlocks every stage without
    clearing any of them, so a learner is never hard-blocked from a topic they
    want to revisit (or an instructor from a stage they want to demonstrate).
    """

    records: tuple[StageRecord, ...] = field(default_factory=tuple)
    practice_mode: bool = False

    # -- lookups ----------------------------------------------------------- #
    def record(self, scenario_name: str) -> StageRecord | None:
        """The record for ``scenario_name``, or ``None`` if never played."""
        for r in self.records:
            if r.scenario_name == scenario_name:
                return r
        return None

    def is_cleared(self, scenario_name: str) -> bool:
        """Whether the learner has passed this stage at least once."""
        record = self.record(scenario_name)
        return record is not None and record.cleared

    def is_unlocked(self, campaign: Campaign, scenario_name: str) -> bool:
        """Whether ``scenario_name`` is playable yet.

        The first stage is always open; every later stage opens once the stage
        before it is cleared. A scenario outside the campaign (an instructor's
        own file, say) is always playable. Practice mode opens everything.
        """
        idx = campaign.index_of(scenario_name)
        if idx <= 0 or self.practice_mode:
            return True
        return self.is_cleared(campaign.stages[idx - 1].scenario_name)

    def cleared_count(self, campaign: Campaign) -> int:
        """How many campaign stages have been cleared."""
        return sum(1 for s in campaign.stages if self.is_cleared(s.scenario_name))

    def medal_counts(self, campaign: Campaign) -> dict[str, int]:
        """Medals earned across the campaign, keyed by medal name."""
        counts = {name: 0 for _threshold, name in MEDAL_THRESHOLDS}
        for stage in campaign.stages:
            record = self.record(stage.scenario_name)
            if record is not None and record.medal:
                counts[record.medal] += 1
        return counts

    def next_stage(self, campaign: Campaign) -> CampaignStage | None:
        """The first uncleared stage — where "continue" should resume.

        ``None`` once every stage is cleared.
        """
        for stage in campaign.stages:
            if not self.is_cleared(stage.scenario_name):
                return stage
        return None

    def is_complete(self, campaign: Campaign) -> bool:
        """Whether every stage in the campaign has been cleared."""
        return self.next_stage(campaign) is None

    # -- updates ----------------------------------------------------------- #
    def with_result(
        self, stage: CampaignStage, ratio: float, score: float
    ) -> CampaignProgress:
        """Record one completed attempt at ``stage`` and return the new progress.

        The play count always increments; ``best_ratio`` / ``best_score`` only
        improve, and ``cleared`` latches once ``ratio`` reaches the stage's
        ``pass_ratio``.
        """
        existing = self.record(stage.scenario_name)
        if existing is None:
            existing = StageRecord(scenario_name=stage.scenario_name)
        updated = replace(
            existing,
            plays=existing.plays + 1,
            cleared=existing.cleared or ratio >= stage.pass_ratio,
            best_ratio=max(existing.best_ratio, ratio),
            best_score=max(existing.best_score, score),
        )
        others = tuple(
            r for r in self.records if r.scenario_name != updated.scenario_name
        )
        return replace(self, records=others + (updated,))

    def with_practice_mode(self, enabled: bool) -> CampaignProgress:
        """Return a copy with practice (unlock-everything) mode set."""
        return replace(self, practice_mode=enabled)

    def reset(self) -> CampaignProgress:
        """Return empty progress, keeping the practice-mode preference."""
        return CampaignProgress(records=(), practice_mode=self.practice_mode)

    # -- serialization ----------------------------------------------------- #
    def to_dict(self) -> dict[str, Any]:
        return {
            "practice_mode": self.practice_mode,
            "stages": [r.to_dict() for r in self.records],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CampaignProgress:
        """Rebuild progress from :meth:`to_dict`, ignoring malformed records."""
        records: list[StageRecord] = []
        for raw in data.get("stages", ()):
            try:
                records.append(StageRecord.from_dict(raw))
            except (KeyError, TypeError, ValueError):
                continue  # a corrupt record loses one stage, not the whole file
        return cls(
            records=tuple(records),
            practice_mode=bool(data.get("practice_mode", False)),
        )
