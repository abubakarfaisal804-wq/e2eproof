from __future__ import annotations

from datetime import UTC, datetime

from .schemas import (
    ActionCandidate,
    ActionKind,
    ApprovalDecision,
    ApprovalRecord,
    PolicyAssessment,
    PolicyStatus,
    PolicyTag,
)

SAFE_DRY_RUN_ACTIONS = (
    ActionKind.OBSERVE,
    ActionKind.SCORE,
    ActionKind.PERSIST_STATE,
    ActionKind.GENERATE_BRIEF,
    ActionKind.READ_ONLY_CHECKS,
)
PROHIBITED_ACTIONS = (
    ActionKind.MODIFY_APPLICATION_CODE,
    ActionKind.OPEN_OR_MERGE_PR,
    ActionKind.SEND_EMAIL,
    ActionKind.DEPLOY,
    ActionKind.PUBLISH_RELEASE,
    ActionKind.CHANGE_CREDENTIALS,
    ActionKind.SPEND_MONEY,
    ActionKind.CHANGE_PRICING_OR_BILLING,
    ActionKind.MAKE_LEGAL_COMMITMENT,
    ActionKind.ACCESS_CUSTOMER_PRODUCTION_DATA,
    ActionKind.DESTRUCTIVE_MIGRATION,
    ActionKind.CHANGE_SECURITY_CONTROL,
    ActionKind.FORCE_PUSH,
    ActionKind.REWRITE_PROTECTED_HISTORY,
)
HARD_BLOCKED_TAGS = {PolicyTag.FORCE_PUSH, PolicyTag.PROTECTED_HISTORY_REWRITE}
APPROVAL_REQUIRED_TAGS = set(PolicyTag) - HARD_BLOCKED_TAGS
ACTION_POLICY_TAGS: dict[ActionKind, set[PolicyTag]] = {
    ActionKind.DEPLOY: {PolicyTag.DEPLOYMENT},
    ActionKind.PUBLISH_RELEASE: {PolicyTag.RELEASE},
    ActionKind.CHANGE_CREDENTIALS: {PolicyTag.CREDENTIALS, PolicyTag.SECRETS},
    ActionKind.SPEND_MONEY: {PolicyTag.SPENDING},
    ActionKind.CHANGE_PRICING_OR_BILLING: {PolicyTag.PRICING, PolicyTag.BILLING},
    ActionKind.MAKE_LEGAL_COMMITMENT: {PolicyTag.LEGAL},
    ActionKind.ACCESS_CUSTOMER_PRODUCTION_DATA: {PolicyTag.CUSTOMER_PRODUCTION_DATA},
    ActionKind.DESTRUCTIVE_MIGRATION: {PolicyTag.DESTRUCTIVE_MIGRATION},
    ActionKind.CHANGE_SECURITY_CONTROL: {PolicyTag.SECURITY_CONTROLS},
    ActionKind.FORCE_PUSH: {PolicyTag.FORCE_PUSH},
    ActionKind.REWRITE_PROTECTED_HISTORY: {PolicyTag.PROTECTED_HISTORY_REWRITE},
}


def effective_policy_tags(candidate: ActionCandidate) -> set[PolicyTag]:
    tags = set(candidate.policy_tags)
    for action in candidate.requested_actions:
        tags.update(ACTION_POLICY_TAGS.get(action, set()))
    return tags


def _is_current(approval: ApprovalRecord, now: datetime) -> bool:
    if approval.decision is not ApprovalDecision.APPROVED:
        return False
    if approval.expires_at is None:
        return True
    expires = approval.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return expires > now


def assess_policy(
    candidate: ActionCandidate,
    approvals: list[ApprovalRecord],
    *,
    now: datetime,
) -> PolicyAssessment:
    tags = effective_policy_tags(candidate)
    hard_blocked = sorted(tags & HARD_BLOCKED_TAGS, key=str)
    required = sorted(tags & APPROVAL_REQUIRED_TAGS, key=str)
    current = [
        item for item in approvals if item.task_id == candidate.task_id and _is_current(item, now)
    ]
    approved_scopes = {scope for item in current for scope in item.scopes}
    missing = [scope for scope in required if scope not in approved_scopes]
    approval_ids = sorted(item.approval_id for item in current)

    if hard_blocked:
        return PolicyAssessment(
            status=PolicyStatus.HARD_BLOCKED,
            approval_required_for=hard_blocked,
            missing_approval_scopes=hard_blocked,
            approval_ids=approval_ids,
            permitted_actions=list(SAFE_DRY_RUN_ACTIONS),
            prohibited_actions=list(PROHIBITED_ACTIONS),
            reason=(
                "Dry-run v1 permanently blocks force pushes and protected-history rewrites; "
                "an approval record cannot enable execution."
            ),
        )
    if missing:
        return PolicyAssessment(
            status=PolicyStatus.OWNER_APPROVAL_REQUIRED,
            approval_required_for=required,
            missing_approval_scopes=missing,
            approval_ids=approval_ids,
            permitted_actions=list(SAFE_DRY_RUN_ACTIONS),
            prohibited_actions=list(PROHIBITED_ACTIONS),
            reason="Owner approval is missing for: " + ", ".join(item.value for item in missing),
        )
    if required:
        return PolicyAssessment(
            status=PolicyStatus.APPROVED_FOR_BRIEF_ONLY,
            approval_required_for=required,
            missing_approval_scopes=[],
            approval_ids=approval_ids,
            permitted_actions=list(SAFE_DRY_RUN_ACTIONS),
            prohibited_actions=list(PROHIBITED_ACTIONS),
            reason=(
                "Recorded owner approval satisfies the policy scopes, but dry-run v1 still "
                "cannot execute the external action."
            ),
        )
    return PolicyAssessment(
        status=PolicyStatus.DRY_RUN_ONLY,
        approval_required_for=[],
        missing_approval_scopes=[],
        approval_ids=[],
        permitted_actions=list(SAFE_DRY_RUN_ACTIONS),
        prohibited_actions=list(PROHIBITED_ACTIONS),
        reason="The brief may be generated, but dry-run v1 performs no external action.",
    )
