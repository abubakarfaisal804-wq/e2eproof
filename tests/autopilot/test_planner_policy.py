from __future__ import annotations

from datetime import timedelta

import pytest

from e2eproof.autopilot.planner import plan_one_action
from e2eproof.autopilot.policy import PROHIBITED_ACTIONS, assess_policy
from e2eproof.autopilot.schemas import (
    ActionKind,
    ActiveTask,
    ApprovalDecision,
    ApprovalRecord,
    AutopilotState,
    FactKind,
    OutcomeRecord,
    OutcomeStatus,
    PolicyStatus,
    PolicyTag,
    RecommendationRecord,
)
from e2eproof.autopilot.scoring import candidate_fingerprint, evidence_digest

from .helpers import NOW, candidate, observation


def test_planner_selects_exactly_one_highest_score_deterministically() -> None:
    low = candidate("low-task", urgency=1)
    high = candidate("high-task", urgency=5)
    result = plan_one_action([low, high], [observation()], [], AutopilotState())
    assert result.candidate == high
    assert sum(card.eligible for card in result.scorecards) == 2
    assert "deterministic score" in result.summary


def test_duplicate_candidates_keep_only_the_highest_scoring_variant() -> None:
    objective = "Complete one shared objective"
    lower = candidate("duplicate-low", objective=objective, urgency=1).model_copy(
        update={"acceptance_criteria": ["Shared result is verified"]}
    )
    higher = candidate("duplicate-high", objective=objective, urgency=5).model_copy(
        update={"acceptance_criteria": ["Shared result is verified"]}
    )
    result = plan_one_action([lower, higher], [observation()], [], AutopilotState())
    assert result.candidate == higher
    cards = {item.task_id: item for item in result.scorecards}
    assert not cards["duplicate-low"].eligible
    assert cards["duplicate-low"].reason == "duplicate objective and acceptance criteria"


def test_planner_blocks_missing_unverified_duplicate_completed_and_hard_blocked() -> None:
    missing = candidate("missing-task", evidence_ids=["obs.missing"])
    hypothesis = candidate("hypothesis-task")
    hard = candidate("hard-task", policy_tags=[PolicyTag.FORCE_PUSH])
    completed = candidate("completed-task")
    outcome = OutcomeRecord(
        outcome_id="outcome-completed",
        task_id="completed-task",
        recorded_at=NOW,
        status=OutcomeStatus.COMPLETED,
        kind=FactKind.VERIFIED,
        summary="done",
    )
    result = plan_one_action(
        [missing, hypothesis, hard, completed],
        [observation(kind=FactKind.HYPOTHESIS)],
        [outcome],
        AutopilotState(),
    )
    assert result.candidate is None
    reasons = {card.task_id: card.reason for card in result.scorecards}
    assert reasons["missing-task"].startswith("missing evidence")
    assert reasons["hypothesis-task"] == "no verified evidence supports the candidate"
    assert "permanently blocks" in reasons["hard-task"]
    assert "completed outcome" in reasons["completed-task"]


def test_active_task_and_unchanged_cooldown_prevent_recommendation() -> None:
    action = candidate("cooldown-task", cooldown_cycles=5)
    evidence = {"obs.security": observation()}
    digest = evidence_digest(action, evidence)
    state = AutopilotState(
        revision=3,
        recommendations={action.task_id: RecommendationRecord(revision=2, evidence_digest=digest)},
    )
    result = plan_one_action([action], list(evidence.values()), [], state)
    assert result.candidate is None
    assert "cooldown" in result.scorecards[0].reason

    active = ActiveTask(
        task_id=action.task_id,
        candidate_fingerprint=candidate_fingerprint(action),
        selected_cycle_id="cycle-active",
        selected_at=NOW,
        evidence_digest=digest,
    )
    occupied = plan_one_action(
        [action], list(evidence.values()), [], AutopilotState(active_task=active)
    )
    assert occupied.candidate is None
    assert occupied.scorecards == []
    assert "owns the execution slot" in occupied.summary


@pytest.mark.parametrize(
    "tag",
    sorted(set(PolicyTag) - {PolicyTag.FORCE_PUSH, PolicyTag.PROTECTED_HISTORY_REWRITE}),
)
def test_sensitive_scopes_require_current_task_approval(tag: PolicyTag) -> None:
    action = candidate("approval-task", policy_tags=[tag])
    missing = assess_policy(action, [], now=NOW)
    assert missing.status is PolicyStatus.OWNER_APPROVAL_REQUIRED
    assert missing.missing_approval_scopes == [tag]
    assert set(missing.prohibited_actions) == set(PROHIBITED_ACTIONS)

    approval = ApprovalRecord(
        approval_id="approval-current",
        task_id=action.task_id,
        scopes=[tag],
        decision=ApprovalDecision.APPROVED,
        decided_by="repository owner",
        decided_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        evidence="Owner reviewed this exact scope.",
    )
    approved = assess_policy(action, [approval], now=NOW)
    assert approved.status is PolicyStatus.APPROVED_FOR_BRIEF_ONLY
    assert approved.missing_approval_scopes == []
    assert set(approved.prohibited_actions) == set(PROHIBITED_ACTIONS)


def test_expired_wrong_task_and_hard_block_approvals_never_authorize_execution() -> None:
    action = candidate("blocked-task", policy_tags=[PolicyTag.SECURITY_CONTROLS])
    expired = ApprovalRecord(
        approval_id="approval-expired",
        task_id="another-task",
        scopes=[PolicyTag.SECURITY_CONTROLS],
        decision=ApprovalDecision.APPROVED,
        decided_by="owner",
        decided_at=NOW - timedelta(days=2),
        expires_at=NOW - timedelta(days=1),
        evidence="Expired and scoped elsewhere.",
    )
    assert assess_policy(action, [expired], now=NOW).status is PolicyStatus.OWNER_APPROVAL_REQUIRED

    force = candidate("force-task", policy_tags=[PolicyTag.FORCE_PUSH])
    hard = assess_policy(force, [], now=NOW)
    assert hard.status is PolicyStatus.HARD_BLOCKED
    assert PolicyTag.FORCE_PUSH in hard.missing_approval_scopes


def test_non_sensitive_candidate_is_still_dry_run_only() -> None:
    result = assess_policy(candidate("safe-task"), [], now=NOW)
    assert result.status is PolicyStatus.DRY_RUN_ONLY
    assert result.approval_required_for == []
    assert set(result.prohibited_actions) == set(PROHIBITED_ACTIONS)


def test_requested_action_infers_policy_scope_even_when_input_omits_tag() -> None:
    action = candidate("inferred-scope-task").model_copy(
        update={"requested_actions": [ActionKind.PUBLISH_RELEASE]}
    )
    result = assess_policy(action, [], now=NOW)
    assert result.status is PolicyStatus.OWNER_APPROVAL_REQUIRED
    assert result.missing_approval_scopes == [PolicyTag.RELEASE]

    force = candidate("inferred-force-task").model_copy(
        update={"requested_actions": [ActionKind.FORCE_PUSH]}
    )
    planned = plan_one_action([force], [observation()], [], AutopilotState())
    assert planned.candidate is None
    assert "permanently blocks" in planned.scorecards[0].reason
