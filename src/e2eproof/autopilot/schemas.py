from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

SCHEMA_VERSION = 1
_TASK_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,99}$")
_CREDENTIAL_PATTERNS = (
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?:ghp|github_pat)_[A-Za-z0-9_]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
_FORBIDDEN_STATE_KEYS = {
    "chain_of_thought",
    "complete_email",
    "email_body",
    "email_html",
    "email_text",
    "full_email",
    "message_body",
    "model_response",
    "prompt",
    "raw_email",
    "reasoning_trace",
}


def ensure_safe_payload(value: object, path: str = "payload") -> None:
    """Reject data that must never enter persistent Autopilot state."""
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key).casefold().replace("-", "_")
            if key in _FORBIDDEN_STATE_KEYS:
                raise ValueError(f"{path}.{raw_key} is prohibited in persistent state")
            ensure_safe_payload(child, f"{path}.{raw_key}")
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            ensure_safe_payload(child, f"{path}[{index}]")
        return
    if isinstance(value, str):
        if len(value) > 20_000:
            raise ValueError(f"{path} exceeds the persistent-state text limit")
        for pattern in _CREDENTIAL_PATTERNS:
            if pattern.search(value):
                raise ValueError(f"{path} appears to contain a literal credential")


class AutopilotModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @model_validator(mode="after")
    def datetime_fields_are_timezone_aware(self) -> AutopilotModel:
        for value in self.__dict__.values():
            if isinstance(value, datetime) and value.tzinfo is None:
                raise ValueError("persistent timestamps must include a timezone")
        return self


class FactKind(StrEnum):
    VERIFIED = "verified"
    ESTIMATE = "estimate"
    HYPOTHESIS = "hypothesis"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CandidateStatus(StrEnum):
    QUEUED = "queued"
    ACTIVE = "active"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    DISMISSED = "dismissed"


class OutcomeStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ApprovalDecision(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


class PolicyTag(StrEnum):
    SPENDING = "spending"
    PAID_INFRASTRUCTURE = "paid_infrastructure"
    CREDENTIALS = "credentials"
    SECRETS = "secrets"
    PRICING = "pricing"
    BILLING = "billing"
    LEGAL = "legal"
    CUSTOMER_PRODUCTION_DATA = "customer_production_data"
    RELEASE = "release"
    DEPLOYMENT = "deployment"
    DESTRUCTIVE_MIGRATION = "destructive_migration"
    BRANCH_PROTECTION = "branch_protection"
    SECURITY_CONTROLS = "security_controls"
    FORCE_PUSH = "force_push"
    PROTECTED_HISTORY_REWRITE = "protected_history_rewrite"


class ActionKind(StrEnum):
    OBSERVE = "observe"
    SCORE = "score"
    PERSIST_STATE = "persist_state"
    GENERATE_BRIEF = "generate_execution_brief"
    READ_ONLY_CHECKS = "run_read_only_checks"
    MODIFY_APPLICATION_CODE = "modify_application_code"
    OPEN_OR_MERGE_PR = "open_or_merge_pull_request"
    SEND_EMAIL = "send_email"
    DEPLOY = "deploy"
    PUBLISH_RELEASE = "publish_release"
    CHANGE_CREDENTIALS = "change_credentials"
    SPEND_MONEY = "spend_money"
    CHANGE_PRICING_OR_BILLING = "change_pricing_or_billing"
    MAKE_LEGAL_COMMITMENT = "make_legal_commitment"
    ACCESS_CUSTOMER_PRODUCTION_DATA = "access_customer_production_data"
    DESTRUCTIVE_MIGRATION = "destructive_migration"
    CHANGE_SECURITY_CONTROL = "change_security_control"
    FORCE_PUSH = "force_push"
    REWRITE_PROTECTED_HISTORY = "rewrite_protected_history"


class PolicyStatus(StrEnum):
    DRY_RUN_ONLY = "dry_run_only"
    OWNER_APPROVAL_REQUIRED = "owner_approval_required"
    APPROVED_FOR_BRIEF_ONLY = "approved_for_brief_only"
    HARD_BLOCKED = "hard_blocked"


class CycleStatus(StrEnum):
    SELECTED = "selected"
    NO_ACTION = "no_action"
    BLOCKED = "blocked"


class Observation(AutopilotModel):
    observation_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,149}$")
    observed_at: datetime
    kind: FactKind
    category: str = Field(min_length=2, max_length=80)
    source: str = Field(min_length=2, max_length=160)
    summary: str = Field(min_length=1, max_length=1000)
    value: JsonValue = None
    evidence_url: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def state_payload_is_safe(self) -> Observation:
        ensure_safe_payload(self.model_dump(mode="json"))
        return self


class ScoreComponent(AutopilotModel):
    value: int = Field(ge=0, le=5)
    basis: FactKind
    evidence_ids: list[str] = Field(min_length=1, max_length=20)
    note: str = Field(min_length=1, max_length=300)


class ActionCandidate(AutopilotModel):
    task_id: str
    objective: str = Field(min_length=3, max_length=500)
    affected_area: str = Field(min_length=2, max_length=120)
    status: CandidateStatus = CandidateStatus.QUEUED
    evidence_ids: list[str] = Field(min_length=1, max_length=30)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=30)
    required_tests: list[str] = Field(default_factory=list, max_length=30)
    suggested_branch: str = Field(min_length=3, max_length=160)
    risk_level: RiskLevel
    requested_actions: list[ActionKind] = Field(default_factory=list, max_length=30)
    policy_tags: list[PolicyTag] = Field(default_factory=list, max_length=20)
    cooldown_cycles: int = Field(default=2, ge=0, le=100)
    revenue_impact: ScoreComponent
    adoption_impact: ScoreComponent
    urgency: ScoreComponent
    confidence: ScoreComponent
    effort: ScoreComponent
    dependency_value: ScoreComponent
    reversibility: ScoreComponent
    risk: ScoreComponent

    @model_validator(mode="after")
    def valid_task(self) -> ActionCandidate:
        if not _TASK_ID.fullmatch(self.task_id):
            raise ValueError("task_id must be a stable lowercase slug")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("candidate evidence_ids must be unique")
        components = (
            self.revenue_impact,
            self.adoption_impact,
            self.urgency,
            self.confidence,
            self.effort,
            self.dependency_value,
            self.reversibility,
            self.risk,
        )
        unknown = {
            evidence_id
            for component in components
            for evidence_id in component.evidence_ids
            if evidence_id not in self.evidence_ids
        }
        if unknown:
            raise ValueError(
                "score components reference evidence outside candidate evidence_ids: "
                + ", ".join(sorted(unknown))
            )
        ensure_safe_payload(self.model_dump(mode="json"))
        return self


class MetricRecord(AutopilotModel):
    metric_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,99}$")
    name: str = Field(min_length=2, max_length=160)
    value: int | float
    unit: str = Field(min_length=1, max_length=40)
    kind: FactKind
    as_of: datetime
    source: str = Field(min_length=2, max_length=160)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)


class ApprovalRecord(AutopilotModel):
    approval_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,99}$")
    task_id: str
    scopes: list[PolicyTag] = Field(min_length=1, max_length=20)
    decision: ApprovalDecision
    decided_by: str = Field(min_length=2, max_length=160)
    decided_at: datetime | None = None
    expires_at: datetime | None = None
    evidence: str = Field(min_length=2, max_length=500)

    @model_validator(mode="after")
    def decision_has_a_timestamp(self) -> ApprovalRecord:
        if (
            self.decision in {ApprovalDecision.APPROVED, ApprovalDecision.DENIED}
            and self.decided_at is None
        ):
            raise ValueError("approved or denied records require decided_at")
        if (
            self.decided_at is not None
            and self.expires_at is not None
            and self.expires_at <= self.decided_at
        ):
            raise ValueError("expires_at must be later than decided_at")
        return self


class ExperimentRecord(AutopilotModel):
    schema_version: int = SCHEMA_VERSION
    experiment_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,99}$")
    recorded_at: datetime
    kind: FactKind
    status: str = Field(min_length=2, max_length=40)
    hypothesis: str = Field(min_length=3, max_length=1000)
    success_metric_ids: list[str] = Field(default_factory=list, max_length=20)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)


class OutcomeRecord(AutopilotModel):
    schema_version: int = SCHEMA_VERSION
    outcome_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,99}$")
    task_id: str
    recorded_at: datetime
    status: OutcomeStatus
    kind: FactKind
    summary: str = Field(min_length=2, max_length=1000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)


class DecisionRecord(AutopilotModel):
    schema_version: int = SCHEMA_VERSION
    decision_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,99}$")
    cycle_id: str
    recorded_at: datetime
    task_id: str | None = None
    decision: str = Field(min_length=2, max_length=80)
    summary: str = Field(min_length=2, max_length=1000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=30)
    score: int | None = None


class ObservationLedgerRecord(AutopilotModel):
    schema_version: int = SCHEMA_VERSION
    entry_id: str
    cycle_id: str
    observation: Observation


class RiskRecord(AutopilotModel):
    risk_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,99}$")
    summary: str = Field(min_length=2, max_length=500)
    evidence: str = Field(min_length=2, max_length=1000)
    control: str = Field(min_length=2, max_length=1000)
    next_action: str = Field(min_length=2, max_length=1000)
    risk_level: RiskLevel
    kind: FactKind


class BudgetConfig(AutopilotModel):
    api_request_limit: int = Field(default=12, ge=0, le=100)
    api_timeout_seconds: float = Field(default=10.0, ge=0.1, le=60.0)
    api_retries: int = Field(default=2, ge=0, le=5)
    model_call_limit: int = Field(default=0, ge=0, le=0)
    process_timeout_seconds: float = Field(default=15.0, ge=0.1, le=120.0)
    lock_timeout_seconds: float = Field(default=5.0, ge=0.0, le=60.0)
    stale_lock_seconds: int = Field(default=900, ge=30, le=86_400)


class CycleInput(AutopilotModel):
    schema_version: int = Field(default=SCHEMA_VERSION, ge=SCHEMA_VERSION, le=SCHEMA_VERSION)
    cycle_id: str | None = Field(default=None, min_length=3, max_length=160)
    mode: str = Field(default="fake", pattern="^fake$")
    observations: list[Observation] = Field(default_factory=list, max_length=500)
    candidates: list[ActionCandidate] = Field(default_factory=list, max_length=500)
    metrics: list[MetricRecord] = Field(default_factory=list, max_length=500)
    approvals: list[ApprovalRecord] = Field(default_factory=list, max_length=100)
    experiments: list[ExperimentRecord] = Field(default_factory=list, max_length=100)
    outcomes: list[OutcomeRecord] = Field(default_factory=list, max_length=500)
    required_observation_categories: list[str] = Field(
        default_factory=lambda: ["repository", "ci", "security", "dependencies", "release"],
        max_length=30,
    )
    budgets: BudgetConfig = Field(default_factory=BudgetConfig)

    @model_validator(mode="after")
    def input_is_safe(self) -> CycleInput:
        unique_fields = (
            ("observations", [item.observation_id for item in self.observations]),
            ("candidates", [item.task_id for item in self.candidates]),
            ("metrics", [item.metric_id for item in self.metrics]),
            ("approvals", [item.approval_id for item in self.approvals]),
            ("experiments", [item.experiment_id for item in self.experiments]),
            ("outcomes", [item.outcome_id for item in self.outcomes]),
        )
        for name, values in unique_fields:
            if len(set(values)) != len(values):
                raise ValueError(f"{name} must use unique stable IDs")
        ensure_safe_payload(self.model_dump(mode="json"))
        return self


class ScoreCard(AutopilotModel):
    task_id: str
    score: int
    breakdown: dict[str, int]
    verified_evidence_count: int = Field(ge=0)
    eligible: bool
    reason: str = Field(min_length=2, max_length=500)


class PolicyAssessment(AutopilotModel):
    status: PolicyStatus
    approval_required_for: list[PolicyTag]
    missing_approval_scopes: list[PolicyTag]
    approval_ids: list[str]
    permitted_actions: list[ActionKind]
    prohibited_actions: list[ActionKind]
    reason: str = Field(min_length=2, max_length=1000)


class OwnerApprovalStatus(AutopilotModel):
    required: bool
    satisfied: bool
    approval_ids: list[str]
    missing_scopes: list[PolicyTag]


class ExecutionBrief(AutopilotModel):
    schema_version: int = SCHEMA_VERSION
    task_id: str
    objective: str
    evidence: list[Observation]
    expected_impact: str
    acceptance_criteria: list[str]
    affected_area: str
    required_tests: list[str]
    suggested_branch: str
    risk_level: RiskLevel
    permitted_actions: list[ActionKind]
    prohibited_actions: list[ActionKind]
    owner_approval: OwnerApprovalStatus
    dry_run: bool = True


class ActiveTask(AutopilotModel):
    task_id: str
    candidate_fingerprint: str
    selected_cycle_id: str
    selected_at: datetime
    evidence_digest: str
    status: str = Field(default="proposed", pattern="^proposed$")


class RecommendationRecord(AutopilotModel):
    revision: int = Field(ge=0)
    evidence_digest: str = Field(min_length=64, max_length=64)


class ActiveCycle(AutopilotModel):
    cycle_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,159}$")
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    started_at: datetime


class AutopilotState(AutopilotModel):
    schema_version: int = SCHEMA_VERSION
    revision: int = Field(default=0, ge=0)
    active_cycle: ActiveCycle | None = None
    active_task: ActiveTask | None = None
    completed_cycle_ids: list[str] = Field(default_factory=list, max_length=200)
    recommendations: dict[str, RecommendationRecord] = Field(default_factory=dict)
    last_completed_at: datetime | None = None


class BacklogFile(AutopilotModel):
    schema_version: int = SCHEMA_VERSION
    items: list[ActionCandidate] = Field(default_factory=list)


class MetricsFile(AutopilotModel):
    schema_version: int = SCHEMA_VERSION
    items: list[MetricRecord] = Field(default_factory=list)


class ApprovalsFile(AutopilotModel):
    schema_version: int = SCHEMA_VERSION
    items: list[ApprovalRecord] = Field(default_factory=list)


class RisksFile(AutopilotModel):
    schema_version: int = SCHEMA_VERSION
    items: list[RiskRecord] = Field(default_factory=list)


class BudgetUsage(AutopilotModel):
    api_requests: int = Field(default=0, ge=0)
    model_calls: int = Field(default=0, ge=0, le=0)


class CycleOutput(AutopilotModel):
    schema_version: int = SCHEMA_VERSION
    cycle_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,159}$")
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    completed_at: datetime
    status: CycleStatus
    dry_run: bool = True
    decision_summary: str
    selected_task_id: str | None = None
    execution_brief: ExecutionBrief | None = None
    observations: list[Observation]
    scorecards: list[ScoreCard]
    policy: PolicyAssessment | None = None
    budgets: BudgetUsage
    state_revision: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)


def model_dump_jsonable(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json", exclude_none=False)
