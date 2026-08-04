from __future__ import annotations

import hashlib
import json
import re

from .schemas import ActionCandidate, Observation, ScoreCard

WEIGHTS: dict[str, int] = {
    "revenue_impact": 18,
    "adoption_impact": 18,
    "urgency": 16,
    "confidence": 12,
    "effort": -12,
    "dependency_value": 14,
    "reversibility": 8,
    "risk": -18,
}


def candidate_fingerprint(candidate: ActionCandidate) -> str:
    normalized = {
        "objective": re.sub(r"\s+", " ", candidate.objective.casefold()).strip(),
        "affected_area": candidate.affected_area.casefold().strip(),
        "acceptance_criteria": sorted(
            re.sub(r"\s+", " ", item.casefold()).strip() for item in candidate.acceptance_criteria
        ),
    }
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def evidence_digest(candidate: ActionCandidate, observations: dict[str, Observation]) -> str:
    evidence = [
        observations[item].model_dump(mode="json", exclude={"observed_at"})
        for item in sorted(candidate.evidence_ids)
        if item in observations
    ]
    encoded = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def score_candidate(candidate: ActionCandidate, verified_evidence_count: int) -> ScoreCard:
    values = {
        "revenue_impact": candidate.revenue_impact.value,
        "adoption_impact": candidate.adoption_impact.value,
        "urgency": candidate.urgency.value,
        "confidence": candidate.confidence.value,
        "effort": candidate.effort.value,
        "dependency_value": candidate.dependency_value.value,
        "reversibility": candidate.reversibility.value,
        "risk": candidate.risk.value,
    }
    breakdown = {name: value * WEIGHTS[name] for name, value in values.items()}
    return ScoreCard(
        task_id=candidate.task_id,
        score=sum(breakdown.values()),
        breakdown=breakdown,
        verified_evidence_count=verified_evidence_count,
        eligible=True,
        reason="eligible",
    )
