"""Guided-mode coaching: a best-play benchmark and an end-of-run verdict.

The simulator's guided (tutorial) mode needs to answer the learner's two hardest
questions — *what does a good decision look like?* and *did I do well?* — without
pretending there is a single mechanically "correct" answer. It does so by
replaying the same scenario with the model-author's ``recommended`` decision on
each deal (the "best play"), scoring that run with the **existing**
:class:`~duw.scenario.scoring.Scorer`, and comparing the learner's score against
it.

Everything here is pure and headless (no Qt). The one heavy call —
:func:`benchmark_result`, which runs the engine — is isolated so the UI can run
it on a background thread; the comparison functions (:func:`evaluate`,
:func:`on_track_label`) are cheap and operate on already-computed results.

The verdict is a teaching signal, not a grade: the benchmark is one strong
reference play, and the notes attribute the learner's shortfall to the desk
levers the scoring model actually captures (default losses, retained exposure,
conceded spread, limit breaches).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from duw.domain.market import MarketSnapshot
from duw.scenario.engine import ScenarioEngine
from duw.scenario.model import Decision, Scenario, ScenarioResult
from duw.scenario.scoring import RoundScore, Scorer, ScoreResult, ScoringParams


def recommended_decisions(scenario: Scenario) -> dict[str, Decision]:
    """The author's best-play decisions, keyed by trade id.

    Only deals that carry a ``recommended`` decision are included; deals without
    one are left to the engine's default (a decline), so a partially-authored
    scenario still yields a coherent benchmark over the deals it does script.
    """
    return {
        deal.trade_id: deal.recommended
        for deal in scenario.deal_stream
        if deal.recommended is not None
    }


def has_benchmark(scenario: Scenario) -> bool:
    """Whether the scenario scripts enough best-play to compute a benchmark."""
    return bool(recommended_decisions(scenario))


def benchmark_result(
    scenario: Scenario, base_snapshot: MarketSnapshot | None = None
) -> ScenarioResult:
    """Run the scenario with the recommended decisions (the heavy engine call)."""
    engine = ScenarioEngine(scenario, base_snapshot=base_snapshot)
    return engine.run(recommended_decisions(scenario))


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    """The end-of-run comparison of the learner's play to the best-play benchmark.

    ``ratio`` is the learner's risk-adjusted score as a fraction of the target
    (guarded when the target is non-positive). ``band`` is a short label,
    ``headline`` a one-line summary, and ``notes`` the round-by-round attribution
    of where the learner gained or lost ground versus the reference.
    """

    student_score: float
    target_score: float
    ratio: float
    band: str
    headline: str
    notes: tuple[str, ...] = field(default_factory=tuple)


def _money(x: float) -> str:
    return f"{x:,.0f}"


def _by_round(score: ScoreResult) -> dict[int, RoundScore]:
    return {rs.round: rs for rs in score.by_round}


def evaluate(
    scenario: Scenario,
    student_result: ScenarioResult,
    bench_result: ScenarioResult,
    params: ScoringParams | None = None,
) -> Verdict:
    """Compare the learner's run to the best-play run and build a verdict.

    Both runs are scored with the same :class:`Scorer` (so the comparison is
    like-for-like), then the risk-adjusted scores are banded and the per-round
    nets are diffed to explain the gap.
    """
    scorer = Scorer(params)
    student = scorer.score(student_result)
    target = scorer.score(bench_result)

    s, t = student.risk_adjusted_score, target.risk_adjusted_score
    ratio = s / t if t > 0 else (1.0 if s >= t else 0.0)
    band, headline = _band(s, t, ratio)
    notes = _round_notes(scenario, student, target)
    return Verdict(
        student_score=s,
        target_score=t,
        ratio=ratio,
        band=band,
        headline=headline,
        notes=notes,
    )


def _band(student: float, target: float, ratio: float) -> tuple[str, str]:
    """Map the score gap to a band label and a plain-English headline."""
    target_txt = _money(target)
    student_txt = _money(student)
    if student < 0:
        return (
            "Loss-making book",
            f"You finished at {student_txt}, in the red. The best play scored "
            f"about {target_txt}; the notes below show where the loss came from.",
        )
    if ratio >= 0.95:
        return (
            "Top marks",
            f"You scored {student_txt} against a best-play benchmark of "
            f"about {target_txt}. You underwrote this book about as well as it "
            "can be.",
        )
    if ratio >= 0.75:
        return (
            "Solid pass",
            f"You scored {student_txt} versus a best-play benchmark of about "
            f"{target_txt}: a good result with a little left on the table.",
        )
    if ratio >= 0.45:
        return (
            "Getting there",
            f"You scored {student_txt} versus a best-play benchmark of about "
            f"{target_txt}. You are on the right track but gave up meaningful "
            "ground; see below.",
        )
    return (
        "Needs work",
        f"You scored {student_txt} versus a best-play benchmark of about "
        f"{target_txt}. Work through the notes below and try the round again.",
    )


def _round_notes(
    scenario: Scenario, student: ScoreResult, target: ScoreResult
) -> tuple[str, ...]:
    """Explain, round by round, where the learner beat or trailed the benchmark.

    For each round the per-round net P&L is compared; a shortfall is attributed
    to the dominant lever (a taken default loss, less revenue from declining or
    over-collateralizing, or more retained exposure / a breach).
    """
    s_rounds = _by_round(student)
    t_rounds = _by_round(target)
    rounds = sorted(set(s_rounds) | set(t_rounds))
    # Tolerance below which a round is treated as "matched" (avoids nitpicking
    # simulation-scale noise): 1% of the target's magnitude, floored modestly.
    tol = max(abs(target.risk_adjusted_score) * 0.01, 500.0)

    notes: list[str] = []
    for r in rounds:
        sr = s_rounds.get(r)
        tr = t_rounds.get(r)
        s_net = sr.net if sr else 0.0
        t_net = tr.net if tr else 0.0
        label = f"Round {r + 1}"
        # A default loss the best play did not take dominates everything else.
        s_loss = sr.realized_losses if sr else 0.0
        t_loss = tr.realized_losses if tr else 0.0
        if s_loss - t_loss > tol:
            notes.append(
                f"- {label}: a default loss of {_money(s_loss - t_loss)} hit your "
                "book that the best play avoided. The deal needed collateral."
            )
            continue
        if s_net < t_net - tol:
            s_rev = (sr.revenue + sr.cva_collected) if sr else 0.0
            t_rev = (tr.revenue + tr.cva_collected) if tr else 0.0
            s_carry = (sr.exposure_cost + sr.breach_penalty) if sr else 0.0
            t_carry = (tr.exposure_cost + tr.breach_penalty) if tr else 0.0
            if t_rev - s_rev >= s_carry - t_carry:
                notes.append(
                    f"- {label}: you earned {_money(t_rev - s_rev)} less revenue. "
                    "You likely declined a workable deal or over-collateralized, "
                    "conceding spread."
                )
            else:
                notes.append(
                    f"- {label}: you carried {_money(s_carry - t_carry)} more in "
                    "exposure and breach charges than the best play needed to."
                )
        elif s_net > t_net + tol:
            notes.append(
                f"+ {label}: you beat the reference by {_money(s_net - t_net)}, "
                "more return for the risk taken."
            )

    if student.breakdown.realized_losses <= 0.0 and _any_default(scenario):
        notes.append("+ You avoided every scripted default loss on your book.")
    return tuple(notes)


def _any_default(scenario: Scenario) -> bool:
    return bool(scenario.defaults)


# ---------------------------------------------------------------------------
# Skills debrief
# ---------------------------------------------------------------------------

#: Grades a skill can be given, best first.
GRADE_MET = "met"
GRADE_PARTIAL = "partial"
GRADE_MISSED = "missed"


@dataclass(frozen=True)
class SkillGrade:
    """How the learner did on one underwriting skill, versus the best play.

    A single P&L number tells a learner they lost without telling them *which
    part of the job* they got wrong. These grades split the same run into the
    four things a desk is actually judged on — protecting the book, charging for
    the credit, staying competitive, and respecting the limit — so the debrief
    points at a behaviour to change rather than a number to beat.

    ``grade`` is one of :data:`GRADE_MET`, :data:`GRADE_PARTIAL`, or
    :data:`GRADE_MISSED`; ``detail`` says what the learner did and what the
    reference did instead.
    """

    skill: str
    grade: str
    detail: str


def _grade_gap(shortfall: float, tol: float) -> str:
    """Grade a shortfall against the benchmark: within tolerance is a pass."""
    if shortfall <= tol:
        return GRADE_MET
    if shortfall <= tol * 4.0:
        return GRADE_PARTIAL
    return GRADE_MISSED


def skill_report(
    student: ScoreResult, target: ScoreResult, tol: float | None = None
) -> tuple[SkillGrade, ...]:
    """Grade the learner's run against the best play, skill by skill.

    ``tol`` is the money gap treated as "matched" (defaults to 1% of the
    benchmark's magnitude, floored modestly) so simulation-scale noise is not
    read as a mistake. Cheap: operates on two already-computed
    :class:`ScoreResult`\\ s, no engine run.
    """
    s, t = student.breakdown, target.breakdown
    if tol is None:
        tol = max(abs(target.risk_adjusted_score) * 0.01, 500.0)

    grades: list[SkillGrade] = []

    # 1. Protection — did a default land on the book that the reference avoided?
    loss_gap = s.realized_losses - t.realized_losses
    if s.realized_losses <= 0.0:
        detail = "No default loss reached your book."
    elif loss_gap <= tol:
        detail = (
            f"You took {_money(s.realized_losses)} in default losses, about what "
            "the best play could not avoid either."
        )
    else:
        detail = (
            f"{_money(loss_gap)} of default loss landed on your book that the "
            "best play kept off it. Collateral on the failing name was the fix."
        )
    grades.append(
        SkillGrade("Protecting the book", _grade_gap(max(loss_gap, 0.0), tol), detail)
    )

    # 2. Pricing — was the credit risk charged for?
    cva_gap = t.cva_collected - s.cva_collected
    if cva_gap <= tol:
        detail = (
            f"You collected {_money(s.cva_collected)} of CVA, in line with the "
            "reference."
        )
    else:
        detail = (
            f"You collected {_money(cva_gap)} less CVA than the best play, so "
            "credit risk you did take went unpriced — usually a declined deal."
        )
    grades.append(
        SkillGrade("Pricing the credit", _grade_gap(max(cva_gap, 0.0), tol), detail)
    )

    # 3. Competitiveness — was spread conceded or business turned away needlessly?
    rev_gap = t.revenue - s.revenue
    if rev_gap <= tol:
        detail = f"You earned {_money(s.revenue)} of revenue, matching the reference."
    else:
        detail = (
            f"You earned {_money(rev_gap)} less revenue than the best play. You "
            "declined workable business or demanded collateral a healthy name "
            "did not need."
        )
    grades.append(
        SkillGrade("Staying competitive", _grade_gap(max(rev_gap, 0.0), tol), detail)
    )

    # 4. Limit discipline — a breach is binary, so it is graded outright.
    if s.breach_penalty <= 0.0:
        grade, detail = GRADE_MET, "You stayed inside the limit on every deal."
    else:
        grade = GRADE_PARTIAL if t.breach_penalty > 0.0 else GRADE_MISSED
        detail = (
            f"You breached a limit, costing {_money(s.breach_penalty)}. Check "
            "headroom against the incremental exposure before committing."
        )
    grades.append(SkillGrade("Respecting the limit", grade, detail))

    return tuple(grades)


# ---------------------------------------------------------------------------
# Live "on track" gauge (cheap; called each round during play)
# ---------------------------------------------------------------------------


def cumulative_net(score: ScoreResult, up_to_round: int) -> float:
    """Sum the per-round net P&L of ``score`` for rounds ``<= up_to_round``."""
    return sum(rs.net for rs in score.by_round if rs.round <= up_to_round)


def on_track_label(student_net: float, benchmark_net: float) -> str:
    """A short live indicator comparing running P&L to the best-play pace.

    Both inputs are cumulative net P&L over the rounds surfaced so far, so the
    comparison is like-for-like as the scenario progresses.
    """
    if benchmark_net <= 0.0:
        return "On track" if student_net >= benchmark_net else "Behind"
    if student_net >= benchmark_net * 1.05:
        return "Ahead of the best play"
    if student_net >= benchmark_net * 0.9:
        return "On track"
    if student_net >= benchmark_net * 0.5:
        return "Slightly behind"
    return "Behind"
