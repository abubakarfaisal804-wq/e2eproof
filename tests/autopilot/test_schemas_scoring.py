from __future__ import annotations

import json
from datetime import timedelta

import pytest
from pydantic import ValidationError

from e2eproof.autopilot.schemas import (
    ApprovalDecision,
    ApprovalRecord,
    BudgetConfig,
    CycleInput,
    FactKind,
    Observation,
    PolicyTag,
)
from e2eproof.autopilot.scoring import candidate_fingerprint, evidence_digest, score_candidate

from .helpers import NOW, candidate, observation


def test_score_is_fixed_integer_formula_and_fingerprints_are_stable() -> None:
    action = candidate(
        "score-task",
        revenue=1,
        adoption=2,
        urgency=3,
        confidence=4,
        effort=2,
        dependency=3,
        reversibility=4,
        risk=1,
    )
    card = score_candidate(action, verified_evidence_count=1)
    assert card.score == 18 + 36 + 48 + 48 - 24 + 42 + 32 - 18
    assert card.breakdown["effort"] == -24
    assert candidate_fingerprint(action) == candidate_fingerprint(action.model_copy())
    changed = action.model_copy(update={"objective": "A different objective"})
    assert candidate_fingerprint(action) != candidate_fingerprint(changed)


def test_evidence_digest_is_ordered_and_changes_with_evidence() -> None:
    action = candidate("digest-task", evidence_ids=["obs.security", "obs.ci"])
    evidence = {
        "obs.security": observation(),
        "obs.ci": observation("obs.ci", category="ci"),
    }
    first = evidence_digest(action, evidence)
    second = evidence_digest(action, dict(reversed(list(evidence.items()))))
    assert first == second
    evidence["obs.ci"] = evidence["obs.ci"].model_copy(
        update={"observed_at": NOW + timedelta(hours=1)}
    )
    assert evidence_digest(action, evidence) == first
    evidence["obs.ci"] = evidence["obs.ci"].model_copy(update={"summary": "changed"})
    assert evidence_digest(action, evidence) != first


@pytest.mark.parametrize(
    "payload",
    [
        {"email_body": "complete personal message"},
        {"chain_of_thought": "hidden reasoning"},
        {"token": "sk-proj-" + "abcdefghijklmnopqrstuvwxyz"},
    ],
)
def test_persistent_observations_reject_prohibited_content(payload: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        Observation(
            observation_id="obs.unsafe",
            observed_at=NOW,
            kind=FactKind.VERIFIED,
            category="security",
            source="test",
            summary="unsafe payload",
            value=payload,
        )


def test_input_is_strict_and_model_budget_is_zero() -> None:
    with pytest.raises(ValidationError):
        BudgetConfig(model_call_limit=1)
    with pytest.raises(ValidationError):
        CycleInput.model_validate(
            {"schema_version": 1, "mode": "fake", "observations": [], "extra": True}
        )
    valid = CycleInput.model_validate_json(json.dumps({"schema_version": 1, "mode": "fake"}))
    assert valid.budgets.model_call_limit == 0


def test_persistent_timestamps_and_approval_decisions_are_explicit() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        Observation(
            observation_id="obs.naive",
            observed_at=NOW.replace(tzinfo=None),
            kind=FactKind.VERIFIED,
            category="security",
            source="test",
            summary="Naive timestamp",
        )
    with pytest.raises(ValidationError, match="decided_at"):
        ApprovalRecord(
            approval_id="approval-without-time",
            task_id="task-without-time",
            scopes=[PolicyTag.RELEASE],
            decision=ApprovalDecision.APPROVED,
            decided_by="owner",
            evidence="Missing timestamp must fail.",
        )
