from __future__ import annotations

from dataclasses import dataclass

from .policy import HARD_BLOCKED_TAGS, effective_policy_tags
from .schemas import (
    ActionCandidate,
    AutopilotState,
    CandidateStatus,
    FactKind,
    Observation,
    OutcomeRecord,
    OutcomeStatus,
    ScoreCard,
)
from .scoring import candidate_fingerprint, evidence_digest, score_candidate


@dataclass(frozen=True)
class PlanSelection:
    candidate: ActionCandidate | None
    scorecards: list[ScoreCard]
    evidence_digest: str | None
    summary: str


def plan_one_action(
    candidates: list[ActionCandidate],
    observations: list[Observation],
    outcomes: list[OutcomeRecord],
    state: AutopilotState,
) -> PlanSelection:
    if state.active_task is not None:
        return PlanSelection(
            candidate=None,
            scorecards=[],
            evidence_digest=None,
            summary=f"Active task {state.active_task.task_id} already owns the execution slot.",
        )

    observation_by_id = {item.observation_id: item for item in observations}
    completed_tasks = {item.task_id for item in outcomes if item.status is OutcomeStatus.COMPLETED}
    scorecards: list[ScoreCard] = []
    eligible: list[tuple[ActionCandidate, ScoreCard, str]] = []

    for candidate in sorted(candidates, key=lambda item: item.task_id):
        reason: str | None = None
        if candidate.status is not CandidateStatus.QUEUED:
            reason = f"candidate status is {candidate.status.value}"
        elif candidate.task_id in completed_tasks:
            reason = "a verified completed outcome already exists"
        elif effective_policy_tags(candidate) & HARD_BLOCKED_TAGS:
            reason = "policy permanently blocks the requested history rewrite"

        missing = [item for item in candidate.evidence_ids if item not in observation_by_id]
        verified_count = sum(
            1
            for item in candidate.evidence_ids
            if item in observation_by_id and observation_by_id[item].kind is FactKind.VERIFIED
        )
        if reason is None and missing:
            reason = "missing evidence: " + ", ".join(sorted(missing))
        if reason is None and verified_count == 0:
            reason = "no verified evidence supports the candidate"

        digest = evidence_digest(candidate, observation_by_id)
        previous = state.recommendations.get(candidate.task_id)
        if (
            reason is None
            and previous is not None
            and previous.evidence_digest == digest
            and state.revision - previous.revision < candidate.cooldown_cycles
        ):
            reason = "unchanged evidence is still inside the recommendation cooldown"

        card = score_candidate(candidate, verified_count)
        if reason is not None:
            card = card.model_copy(update={"eligible": False, "reason": reason})
        else:
            eligible.append((candidate, card, digest))
        scorecards.append(card)

    if not eligible:
        return PlanSelection(
            candidate=None,
            scorecards=scorecards,
            evidence_digest=None,
            summary="No eligible non-duplicate action has sufficient verified evidence.",
        )

    eligible.sort(
        key=lambda item: (
            -item[1].score,
            item[0].risk.value,
            item[0].effort.value,
            item[0].task_id,
        )
    )
    unique: list[tuple[ActionCandidate, ScoreCard, str]] = []
    seen_fingerprints: set[str] = set()
    for item in eligible:
        fingerprint = candidate_fingerprint(item[0])
        if fingerprint in seen_fingerprints:
            scorecards = [
                card.model_copy(
                    update={
                        "eligible": False,
                        "reason": "duplicate objective and acceptance criteria",
                    }
                )
                if card.task_id == item[0].task_id
                else card
                for card in scorecards
            ]
            continue
        seen_fingerprints.add(fingerprint)
        unique.append(item)
    eligible = unique
    selected, card, digest = eligible[0]
    return PlanSelection(
        candidate=selected,
        scorecards=scorecards,
        evidence_digest=digest,
        summary=f"Selected {selected.task_id} with deterministic score {card.score}.",
    )
