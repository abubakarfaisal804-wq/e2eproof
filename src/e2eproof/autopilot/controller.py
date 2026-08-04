from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .audit import AuditLog
from .errors import AutopilotError
from .locking import ProcessLock
from .observer import GitHubObserver, observe_local_repository
from .planner import plan_one_action
from .policy import assess_policy
from .schemas import (
    ActiveCycle,
    ActiveTask,
    ApprovalsFile,
    AutopilotState,
    BacklogFile,
    BudgetUsage,
    CycleInput,
    CycleOutput,
    CycleStatus,
    DecisionRecord,
    ExecutionBrief,
    FactKind,
    Observation,
    ObservationLedgerRecord,
    OutcomeRecord,
    OutcomeStatus,
    OwnerApprovalStatus,
    PolicyAssessment,
    RecommendationRecord,
    ensure_safe_payload,
)
from .scoring import candidate_fingerprint
from .state import StateStore

_CYCLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,159}$")


def load_cycle_input(path: Path) -> CycleInput:
    try:
        return CycleInput.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise AutopilotError(f"Could not load Autopilot input: {error}") from error


def _cycle_id(cycle_input: CycleInput, override: str | None) -> str:
    selected = override or cycle_input.cycle_id
    if selected is None:
        canonical = json.dumps(
            cycle_input.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        selected = "cycle-" + hashlib.sha256(canonical).hexdigest()[:24]
    if not _CYCLE_ID.fullmatch(selected):
        raise AutopilotError("cycle_id must be a safe filename-compatible identifier")
    return selected


def _input_digest(cycle_input: CycleInput) -> str:
    canonical = json.dumps(
        cycle_input.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _expected_impact(candidate: object, score: int) -> str:
    from .schemas import ActionCandidate

    if not isinstance(candidate, ActionCandidate):
        raise TypeError("candidate must be an ActionCandidate")
    return (
        f"Deterministic priority score {score}; revenue impact "
        f"{candidate.revenue_impact.value}/5 ({candidate.revenue_impact.basis.value}), adoption "
        f"impact {candidate.adoption_impact.value}/5 ({candidate.adoption_impact.basis.value}), "
        f"and reliability urgency {candidate.urgency.value}/5 "
        f"({candidate.urgency.basis.value})."
    )


def _brief(
    candidate: object,
    observations: dict[str, Observation],
    score: int,
    policy: PolicyAssessment,
) -> ExecutionBrief:
    from .schemas import ActionCandidate

    if not isinstance(candidate, ActionCandidate):
        raise TypeError("candidate must be an ActionCandidate")
    missing = set(policy.missing_approval_scopes)
    return ExecutionBrief(
        task_id=candidate.task_id,
        objective=candidate.objective,
        evidence=[observations[item] for item in candidate.evidence_ids if item in observations],
        expected_impact=_expected_impact(candidate, score),
        acceptance_criteria=candidate.acceptance_criteria,
        affected_area=candidate.affected_area,
        required_tests=candidate.required_tests,
        suggested_branch=candidate.suggested_branch,
        risk_level=candidate.risk_level,
        permitted_actions=policy.permitted_actions,
        prohibited_actions=policy.prohibited_actions,
        owner_approval=OwnerApprovalStatus(
            required=bool(policy.approval_required_for),
            satisfied=not missing,
            approval_ids=policy.approval_ids,
            missing_scopes=list(missing),
        ),
    )


def _reconcile_cached_state(store: StateStore, state: AutopilotState, cached: CycleOutput) -> bool:
    if cached.cycle_id in state.completed_cycle_ids and state.active_cycle is None:
        return False
    completed = [*state.completed_cycle_ids, cached.cycle_id][-200:]
    updated = state.model_copy(
        update={
            "revision": max(state.revision, cached.state_revision),
            "active_cycle": None,
            "completed_cycle_ids": completed,
            "last_completed_at": cached.completed_at,
        }
    )
    store.write_model("state.json", updated)
    return True


def run_dry_cycle(
    cycle_input: CycleInput,
    *,
    repository_root: Path,
    state_dir: Path,
    seed_dir: Path | None = None,
    cycle_id_override: str | None = None,
    github_live: bool = False,
    github_repository: str | None = None,
    github_token: str | None = None,
    github_transport: httpx.BaseTransport | None = None,
    now: datetime | None = None,
) -> CycleOutput:
    current_time = now or datetime.now(UTC)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=UTC)
    cycle_id = _cycle_id(cycle_input, cycle_id_override)
    input_digest = _input_digest(cycle_input)
    store = StateStore(state_dir)
    lock = ProcessLock(
        store.path(".autopilot.lock"),
        timeout_seconds=cycle_input.budgets.lock_timeout_seconds,
        stale_after_seconds=cycle_input.budgets.stale_lock_seconds,
    )
    with lock:
        store.initialize(seed_dir)
        audit = AuditLog(store.root)
        valid, detail = audit.verify()
        if not valid:
            raise AutopilotError(f"Existing audit chain verification failed: {detail}")
        state = store.read_model("state.json", AutopilotState)
        cached = store.cached_result(cycle_id)
        if cached is not None:
            if cached.input_digest != input_digest:
                raise AutopilotError(
                    "cycle_id was reused with different structured input; choose a new cycle_id"
                )
            if _reconcile_cached_state(store, state, cached):
                audit.append(
                    event_id=f"{cycle_id}.cached-state-reconciled",
                    cycle_id=cycle_id,
                    recorded_at=current_time,
                    event_type="cached_state_reconciled",
                    data={"state_revision": cached.state_revision},
                )
            return cached

        warnings: list[str] = []
        if lock.recovered_stale_lock:
            warnings.append("Recovered a stale process lock.")
            audit.append(
                event_id=f"{cycle_id}.stale-lock-recovered",
                cycle_id=cycle_id,
                recorded_at=current_time,
                event_type="stale_lock_recovered",
                data={},
            )
        if state.active_cycle is not None:
            if (
                state.active_cycle.cycle_id == cycle_id
                and state.active_cycle.input_digest != input_digest
            ):
                raise AutopilotError(
                    "interrupted cycle_id was reused with different structured input; "
                    "choose a new cycle_id"
                )
            warnings.append(f"Recovered interrupted cycle {state.active_cycle.cycle_id}.")
            audit.append(
                event_id=f"{cycle_id}.interrupted-cycle-recovered",
                cycle_id=cycle_id,
                recorded_at=current_time,
                event_type="interrupted_cycle_recovered",
                data={"previous_cycle_id": state.active_cycle.cycle_id},
            )

        state = state.model_copy(
            update={
                "active_cycle": ActiveCycle(
                    cycle_id=cycle_id,
                    input_digest=input_digest,
                    started_at=current_time,
                )
            }
        )
        store.write_model("state.json", state)
        audit.append(
            event_id=f"{cycle_id}.started",
            cycle_id=cycle_id,
            recorded_at=current_time,
            event_type="cycle_started",
            data={"mode": "fake", "dry_run": True},
        )

        local = observe_local_repository(
            repository_root,
            now=current_time,
            process_timeout_seconds=cycle_input.budgets.process_timeout_seconds,
        )
        observations = {item.observation_id: item for item in cycle_input.observations}
        observations.update({item.observation_id: item for item in local})
        prior_decisions = store.read_jsonl_models("decisions.jsonl", DecisionRecord)
        prior_outcomes = store.read_jsonl_models("outcomes.jsonl", OutcomeRecord)
        observations["state.coordination_history"] = Observation(
            observation_id="state.coordination_history",
            observed_at=current_time,
            kind=FactKind.VERIFIED,
            category="coordination_state",
            source="versioned Autopilot state ledgers",
            summary="Observed the active task and compact prior decision and outcome records.",
            value={
                "active_task": (
                    {
                        "task_id": state.active_task.task_id,
                        "status": state.active_task.status,
                        "selected_cycle_id": state.active_task.selected_cycle_id,
                    }
                    if state.active_task is not None
                    else None
                ),
                "decisions": [
                    {
                        "decision_id": item.decision_id,
                        "task_id": item.task_id,
                        "decision": item.decision,
                        "recorded_at": item.recorded_at.isoformat(),
                    }
                    for item in prior_decisions[-50:]
                ],
                "completed_outcomes": [
                    {
                        "outcome_id": item.outcome_id,
                        "task_id": item.task_id,
                        "status": item.status.value,
                        "recorded_at": item.recorded_at.isoformat(),
                    }
                    for item in prior_outcomes[-50:]
                    if item.status is OutcomeStatus.COMPLETED
                ],
            },
        )
        api_requests = 0
        live_complete = True
        if github_live:
            if github_repository is None or github_token is None:
                raise AutopilotError(
                    "github_repository and github_token are required with --github-live"
                )
            report = GitHubObserver(
                repository=github_repository,
                token=github_token,
                budgets=cycle_input.budgets,
                transport=github_transport,
            ).observe(now=current_time)
            observations.update({item.observation_id: item for item in report.observations})
            api_requests = report.api_requests
            live_complete = report.complete and not report.errors
            warnings.extend(report.errors)

        persisted_cycle_observations = {
            item.observation.observation_id: item.observation
            for item in store.read_jsonl_models("observations.jsonl", ObservationLedgerRecord)
            if item.cycle_id == cycle_id
        }
        if persisted_cycle_observations:
            observations.update(persisted_cycle_observations)
            warnings.append("Reused observations already persisted by the interrupted cycle.")
        observation_items = [observations[key] for key in sorted(observations)]
        for observation in observation_items:
            store.append_unique(
                "observations.jsonl",
                ObservationLedgerRecord(
                    entry_id=f"{cycle_id}:{observation.observation_id}",
                    cycle_id=cycle_id,
                    observation=observation,
                ),
                key="entry_id",
            )
        store.merge_cycle_input(cycle_input)

        persisted_outcomes = store.read_jsonl_models("outcomes.jsonl", OutcomeRecord)
        if state.active_task is not None:
            terminal_tasks = {item.task_id for item in persisted_outcomes}
            if state.active_task.task_id in terminal_tasks:
                state = state.model_copy(update={"active_task": None})

        verified_categories = {
            item.category for item in observation_items if item.kind is FactKind.VERIFIED
        }
        missing_categories = sorted(
            set(cycle_input.required_observation_categories) - verified_categories
        )
        backlog = store.read_model("backlog.json", BacklogFile)
        approvals = store.read_model("approvals.json", ApprovalsFile)
        selection = plan_one_action(backlog.items, observation_items, persisted_outcomes, state)

        policy: PolicyAssessment | None = None
        brief: ExecutionBrief | None = None
        selected_task_id: str | None = None
        status = CycleStatus.NO_ACTION
        decision_summary = selection.summary
        next_revision = state.revision + 1

        if missing_categories or not live_complete:
            status = CycleStatus.BLOCKED
            details = []
            if missing_categories:
                details.append("missing verified categories: " + ", ".join(missing_categories))
            if not live_complete:
                details.append("live observation was incomplete")
            decision_summary = "Fail-closed planning block: " + "; ".join(details)
        elif selection.candidate is not None and selection.evidence_digest is not None:
            candidate = selection.candidate
            selected_card = next(
                item for item in selection.scorecards if item.task_id == candidate.task_id
            )
            policy = assess_policy(candidate, approvals.items, now=current_time)
            brief = _brief(candidate, observations, selected_card.score, policy)
            selected_task_id = candidate.task_id
            status = CycleStatus.SELECTED
            state = state.model_copy(
                update={
                    "active_task": ActiveTask(
                        task_id=candidate.task_id,
                        candidate_fingerprint=candidate_fingerprint(candidate),
                        selected_cycle_id=cycle_id,
                        selected_at=current_time,
                        evidence_digest=selection.evidence_digest,
                    ),
                    "recommendations": {
                        **state.recommendations,
                        candidate.task_id: RecommendationRecord(
                            revision=next_revision,
                            evidence_digest=selection.evidence_digest,
                        ),
                    },
                }
            )

        decision = DecisionRecord(
            decision_id=("decision-" + hashlib.sha256(cycle_id.encode("utf-8")).hexdigest()[:24]),
            cycle_id=cycle_id,
            recorded_at=current_time,
            task_id=selected_task_id,
            decision=status.value,
            summary=decision_summary,
            evidence_ids=(
                selection.candidate.evidence_ids if selection.candidate is not None else []
            ),
            score=(
                next(
                    item.score for item in selection.scorecards if item.task_id == selected_task_id
                )
                if selected_task_id is not None
                else None
            ),
        )
        store.append_unique("decisions.jsonl", decision, key="decision_id")

        output = CycleOutput(
            cycle_id=cycle_id,
            input_digest=input_digest,
            completed_at=current_time,
            status=status,
            decision_summary=decision_summary,
            selected_task_id=selected_task_id,
            execution_brief=brief,
            observations=observation_items,
            scorecards=selection.scorecards,
            policy=policy,
            budgets=BudgetUsage(api_requests=api_requests, model_calls=0),
            state_revision=next_revision,
            warnings=warnings,
        )
        completed_ids = [item for item in state.completed_cycle_ids if item != cycle_id] + [
            cycle_id
        ]
        state = state.model_copy(
            update={
                "revision": next_revision,
                "active_cycle": None,
                "completed_cycle_ids": completed_ids[-200:],
                "last_completed_at": current_time,
            }
        )
        store.write_cycle_result(output)
        store.write_model("state.json", state)
        audit.append(
            event_id=f"{cycle_id}.completed",
            cycle_id=cycle_id,
            recorded_at=current_time,
            event_type="cycle_completed",
            data={"status": status.value, "selected_task_id": selected_task_id},
        )
        valid, detail = audit.verify()
        if not valid:
            raise AutopilotError(f"Audit chain verification failed: {detail}")
        return output


def render_summary(output: CycleOutput) -> str:
    lines = [
        "# E2EProof Autopilot dry-run",
        "",
        f"- Cycle: `{output.cycle_id}`",
        f"- Status: `{output.status.value}`",
        f"- State revision: `{output.state_revision}`",
        f"- GitHub API requests: `{output.budgets.api_requests}`",
        f"- Model calls: `{output.budgets.model_calls}`",
        "",
        "## Decision",
        "",
        output.decision_summary,
    ]
    if output.execution_brief is not None:
        brief = output.execution_brief
        lines.extend(
            [
                "",
                "## Execution brief",
                "",
                f"- Task: `{brief.task_id}`",
                f"- Objective: {brief.objective}",
                f"- Affected area: {brief.affected_area}",
                f"- Risk: `{brief.risk_level.value}`",
                f"- Suggested branch: `{brief.suggested_branch}`",
                f"- Owner approval satisfied: `{brief.owner_approval.satisfied}`",
                "",
                "The control plane generated this brief only. It executed no external action.",
            ]
        )
    if output.warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in output.warnings)
    return "\n".join(lines) + "\n"


def write_artifacts(
    output: CycleOutput,
    *,
    output_path: Path,
    brief_path: Path,
    summary_path: Path,
) -> None:
    payloads: tuple[tuple[Path, str], ...] = (
        (output_path, output.model_dump_json(indent=2) + "\n"),
        (
            brief_path,
            (
                output.execution_brief.model_dump_json(indent=2) + "\n"
                if output.execution_brief is not None
                else json.dumps(
                    {"schema_version": 1, "task_id": None, "status": output.status.value},
                    indent=2,
                )
                + "\n"
            ),
        ),
        (summary_path, render_summary(output)),
    )
    for path, payload in payloads:
        ensure_safe_payload(payload, str(path))
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
