from __future__ import annotations

from datetime import UTC, datetime

from e2eproof.autopilot.schemas import (
    ActionCandidate,
    ActionKind,
    FactKind,
    Observation,
    PolicyTag,
    RiskLevel,
    ScoreComponent,
)

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def component(
    value: int,
    basis: FactKind = FactKind.VERIFIED,
    evidence_ids: list[str] | None = None,
) -> ScoreComponent:
    return ScoreComponent(
        value=value,
        basis=basis,
        evidence_ids=evidence_ids or ["obs.security"],
        note="test",
    )


def candidate(
    task_id: str,
    *,
    objective: str | None = None,
    revenue: int = 0,
    adoption: int = 0,
    urgency: int = 3,
    confidence: int = 3,
    effort: int = 2,
    dependency: int = 2,
    reversibility: int = 4,
    risk: int = 1,
    policy_tags: list[PolicyTag] | None = None,
    evidence_ids: list[str] | None = None,
    cooldown_cycles: int = 2,
) -> ActionCandidate:
    references = evidence_ids or ["obs.security"]
    return ActionCandidate(
        task_id=task_id,
        objective=objective or f"Complete {task_id} safely",
        affected_area="test area",
        evidence_ids=references,
        acceptance_criteria=[f"{task_id} is verified"],
        required_tests=["targeted tests"],
        suggested_branch=f"test/{task_id}",
        risk_level=RiskLevel.LOW,
        requested_actions=[ActionKind.GENERATE_BRIEF],
        policy_tags=policy_tags or [],
        cooldown_cycles=cooldown_cycles,
        revenue_impact=component(revenue, FactKind.HYPOTHESIS, references),
        adoption_impact=component(adoption, FactKind.ESTIMATE, references),
        urgency=component(urgency, evidence_ids=references),
        confidence=component(confidence, evidence_ids=references),
        effort=component(effort, FactKind.ESTIMATE, references),
        dependency_value=component(dependency, FactKind.ESTIMATE, references),
        reversibility=component(reversibility, FactKind.ESTIMATE, references),
        risk=component(risk, FactKind.ESTIMATE, references),
    )


def observation(
    observation_id: str = "obs.security",
    *,
    category: str = "security",
    kind: FactKind = FactKind.VERIFIED,
) -> Observation:
    return Observation(
        observation_id=observation_id,
        observed_at=NOW,
        kind=kind,
        category=category,
        source="test fixture",
        summary=f"Observed {category}",
        value={"ok": True},
    )
