from __future__ import annotations

import json
import os
import time
from datetime import timedelta
from pathlib import Path

import pytest

from e2eproof.autopilot.audit import AuditLog
from e2eproof.autopilot.controller import (
    load_cycle_input,
    render_summary,
    run_dry_cycle,
    write_artifacts,
)
from e2eproof.autopilot.errors import AutopilotError
from e2eproof.autopilot.locking import ProcessLock
from e2eproof.autopilot.schemas import (
    ActiveCycle,
    AutopilotState,
    CycleInput,
    CycleStatus,
    DecisionRecord,
    FactKind,
    OutcomeRecord,
    OutcomeStatus,
)
from e2eproof.autopilot.state import StateStore

from .helpers import NOW, observation

ROOT = Path(__file__).resolve().parents[2]
INPUT_PATH = ROOT / "evals" / "autopilot" / "fixtures" / "local-cycle.json"


def test_state_store_is_confined_atomic_and_jsonl_idempotent(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state")
    store.initialize(ROOT / "ops")
    assert store.read_model("state.json", AutopilotState).revision == 0
    with pytest.raises(AutopilotError, match="escapes"):
        store.path("../outside.json")

    decision = DecisionRecord(
        decision_id="decision-test-state",
        cycle_id="cycle-test-state",
        recorded_at=NOW,
        decision="no_action",
        summary="No eligible action.",
    )
    assert store.append_unique("decisions.jsonl", decision, key="decision_id")
    assert not store.append_unique("decisions.jsonl", decision, key="decision_id")
    with pytest.raises(AutopilotError, match="Conflicting append-only record"):
        store.append_unique(
            "decisions.jsonl",
            decision.model_copy(update={"summary": "Conflicting result."}),
            key="decision_id",
        )
    records = store.read_jsonl_models("decisions.jsonl", DecisionRecord)
    assert records[-1] == decision

    updated = AutopilotState(revision=4)
    store.write_model("state.json", updated)
    assert store.read_model("state.json", AutopilotState) == updated
    assert not list(store.root.glob("*.tmp"))


def test_seed_state_is_validated_before_it_can_be_persisted(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "risks.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "items": [
                    {
                        "risk_id": "unsafe-seed-risk",
                        "summary": "unsafe",
                        "evidence": "sk-proj-" + "abcdefghijklmnopqrstuvwxyz",
                        "control": "none",
                        "next_action": "reject",
                        "risk_level": "high",
                        "kind": "verified",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(AutopilotError, match="literal credential"):
        StateStore(tmp_path / "state").initialize(seed)


def test_lock_is_bounded_and_recovers_only_stale_lock(tmp_path: Path) -> None:
    path = tmp_path / "state" / ".autopilot.lock"
    first = ProcessLock(path, timeout_seconds=0.1, stale_after_seconds=30, poll_seconds=0.01)
    first.acquire()
    try:
        second = ProcessLock(path, timeout_seconds=0.02, stale_after_seconds=30, poll_seconds=0.005)
        with pytest.raises(AutopilotError, match="locked"):
            second.acquire()
    finally:
        first.release()

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    stale_time = time.time() - 31
    os.utime(path, (stale_time, stale_time))
    recovered = ProcessLock(path, timeout_seconds=0.1, stale_after_seconds=30)
    with recovered:
        assert recovered.recovered_stale_lock
        assert path.exists()
    assert not path.exists()


def test_audit_log_is_unique_hash_linked_and_detects_tampering(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path)
    first = audit.append(
        event_id="cycle-a.started",
        cycle_id="cycle-a",
        recorded_at=NOW,
        event_type="cycle_started",
        data={"dry_run": True},
    )
    assert (
        audit.append(
            event_id="cycle-a.started",
            cycle_id="cycle-a",
            recorded_at=NOW,
            event_type="cycle_started",
            data={"dry_run": True},
        )
        == first
    )
    audit.append(
        event_id="cycle-a.completed",
        cycle_id="cycle-a",
        recorded_at=NOW,
        event_type="cycle_completed",
        data={"status": "no_action"},
    )
    assert audit.verify() == (True, "ok")
    lines = audit.path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[1])
    tampered["data"]["status"] = "selected"
    lines[1] = json.dumps(tampered)
    audit.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert audit.verify()[0] is False


def test_controller_selects_one_persists_artifacts_and_replays_idempotently(
    tmp_path: Path,
) -> None:
    cycle_input = load_cycle_input(INPUT_PATH)
    state_dir = tmp_path / "state"
    first = run_dry_cycle(
        cycle_input,
        repository_root=ROOT,
        state_dir=state_dir,
        seed_dir=ROOT / "ops",
        cycle_id_override="controller-cycle-one",
        now=NOW,
    )
    assert first.status is CycleStatus.SELECTED
    assert first.selected_task_id == "enable-dependabot-alerts"
    assert first.execution_brief is not None
    assert first.execution_brief.owner_approval.required
    assert not first.execution_brief.owner_approval.satisfied
    assert first.budgets.model_calls == 0

    output_path = tmp_path / "artifacts" / "result.json"
    brief_path = tmp_path / "artifacts" / "brief.json"
    summary_path = tmp_path / "artifacts" / "summary.md"
    write_artifacts(
        first,
        output_path=output_path,
        brief_path=brief_path,
        summary_path=summary_path,
    )
    assert json.loads(output_path.read_text(encoding="utf-8"))["dry_run"] is True
    assert json.loads(brief_path.read_text(encoding="utf-8"))["task_id"] == first.selected_task_id
    assert "executed no external action" in summary_path.read_text(encoding="utf-8")
    assert render_summary(first).startswith("# E2EProof Autopilot dry-run")

    audit_before = (state_dir / "audit.jsonl").read_text(encoding="utf-8")
    observations_before = (state_dir / "observations.jsonl").read_text(encoding="utf-8")
    replay = run_dry_cycle(
        cycle_input,
        repository_root=ROOT,
        state_dir=state_dir,
        seed_dir=ROOT / "ops",
        cycle_id_override="controller-cycle-one",
        now=NOW + timedelta(hours=1),
    )
    assert replay == first
    assert (state_dir / "audit.jsonl").read_text(encoding="utf-8") == audit_before
    assert (state_dir / "observations.jsonl").read_text(encoding="utf-8") == observations_before

    changed = cycle_input.model_copy(
        update={
            "observations": [
                item.model_copy(update={"summary": item.summary + " changed"})
                if item.observation_id == "github.ci_status"
                else item
                for item in cycle_input.observations
            ]
        }
    )
    with pytest.raises(AutopilotError, match="reused with different"):
        run_dry_cycle(
            changed,
            repository_root=ROOT,
            state_dir=state_dir,
            seed_dir=ROOT / "ops",
            cycle_id_override="controller-cycle-one",
            now=NOW + timedelta(hours=2),
        )


def test_interrupted_cycle_reuses_partial_observation_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cycle_input = load_cycle_input(INPUT_PATH)
    state_dir = tmp_path / "state"
    original_append = StateStore.append_unique
    interrupted = False

    def append_then_interrupt(
        self: StateStore,
        relative: str,
        record,
        *,
        key: str,
    ) -> bool:
        nonlocal interrupted
        result = original_append(self, relative, record, key=key)
        if relative == "observations.jsonl" and not interrupted:
            interrupted = True
            raise RuntimeError("simulated interruption")
        return result

    with monkeypatch.context() as patcher:
        patcher.setattr(StateStore, "append_unique", append_then_interrupt)
        with pytest.raises(RuntimeError, match="simulated interruption"):
            run_dry_cycle(
                cycle_input,
                repository_root=ROOT,
                state_dir=state_dir,
                seed_dir=ROOT / "ops",
                cycle_id_override="partial-cycle",
                now=NOW,
            )

    changed = cycle_input.model_copy(update={"required_observation_categories": ["repository"]})
    with pytest.raises(AutopilotError, match="interrupted cycle_id was reused"):
        run_dry_cycle(
            changed,
            repository_root=ROOT,
            state_dir=state_dir,
            seed_dir=ROOT / "ops",
            cycle_id_override="partial-cycle",
            now=NOW + timedelta(minutes=30),
        )

    recovered = run_dry_cycle(
        cycle_input,
        repository_root=ROOT,
        state_dir=state_dir,
        seed_dir=ROOT / "ops",
        cycle_id_override="partial-cycle",
        now=NOW + timedelta(hours=1),
    )
    assert recovered.status is CycleStatus.SELECTED
    assert "Recovered interrupted cycle partial-cycle." in recovered.warnings
    assert "Reused observations already persisted" in " ".join(recovered.warnings)


def test_active_slot_then_terminal_outcome_allows_next_task(tmp_path: Path) -> None:
    cycle_input = load_cycle_input(INPUT_PATH)
    state_dir = tmp_path / "state"
    run_dry_cycle(
        cycle_input,
        repository_root=ROOT,
        state_dir=state_dir,
        seed_dir=ROOT / "ops",
        cycle_id_override="slot-cycle-one",
        now=NOW,
    )
    occupied = run_dry_cycle(
        cycle_input.model_copy(update={"cycle_id": "slot-cycle-two"}),
        repository_root=ROOT,
        state_dir=state_dir,
        seed_dir=ROOT / "ops",
        now=NOW + timedelta(hours=1),
    )
    assert occupied.status is CycleStatus.NO_ACTION
    assert occupied.selected_task_id is None
    assert "owns the execution slot" in occupied.decision_summary

    outcome = OutcomeRecord(
        outcome_id="outcome-owner-dependabot",
        task_id="enable-dependabot-alerts",
        recorded_at=NOW + timedelta(hours=2),
        status=OutcomeStatus.COMPLETED,
        kind=FactKind.VERIFIED,
        summary="Owner supplied a terminal outcome.",
    )
    next_input = cycle_input.model_copy(
        update={"cycle_id": "slot-cycle-three", "outcomes": [outcome]}
    )
    third = run_dry_cycle(
        next_input,
        repository_root=ROOT,
        state_dir=state_dir,
        seed_dir=ROOT / "ops",
        now=NOW + timedelta(hours=2),
    )
    assert third.status is CycleStatus.SELECTED
    assert third.selected_task_id == "dependency-audit-recurring"


def test_missing_observation_fails_closed_and_recovery_is_recorded(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    store = StateStore(state_dir)
    store.initialize(ROOT / "ops")
    store.write_model(
        "state.json",
        AutopilotState(
            active_cycle=ActiveCycle(
                cycle_id="interrupted-cycle",
                input_digest="0" * 64,
                started_at=NOW,
            )
        ),
    )
    incomplete = CycleInput(
        cycle_id="recovery-cycle",
        observations=[observation("obs.ci", category="ci")],
        required_observation_categories=["repository", "ci", "security", "dependencies"],
    )
    result = run_dry_cycle(
        incomplete,
        repository_root=ROOT,
        state_dir=state_dir,
        seed_dir=ROOT / "ops",
        now=NOW + timedelta(hours=1),
    )
    assert result.status is CycleStatus.BLOCKED
    assert "missing verified categories: security" in result.decision_summary
    assert result.execution_brief is None
    assert result.warnings == ["Recovered interrupted cycle interrupted-cycle."]
    assert "interrupted_cycle_recovered" in (state_dir / "audit.jsonl").read_text(encoding="utf-8")


def test_invalid_cycle_identifier_and_input_fail_before_unsafe_path_use(tmp_path: Path) -> None:
    cycle_input = load_cycle_input(INPUT_PATH)
    with pytest.raises(AutopilotError, match="safe filename"):
        run_dry_cycle(
            cycle_input,
            repository_root=ROOT,
            state_dir=tmp_path / "state",
            cycle_id_override="../escape",
            now=NOW,
        )
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(AutopilotError, match="Could not load"):
        load_cycle_input(bad)
