from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from .errors import AutopilotError
from .schemas import (
    ApprovalsFile,
    AutopilotState,
    BacklogFile,
    CycleInput,
    CycleOutput,
    DecisionRecord,
    ExperimentRecord,
    MetricsFile,
    ObservationLedgerRecord,
    OutcomeRecord,
    RisksFile,
    ensure_safe_payload,
)

ModelT = TypeVar("ModelT", bound=BaseModel)
_SEED_FILES = (
    "state.json",
    "backlog.json",
    "metrics.json",
    "approvals.json",
    "risks.json",
    "observations.jsonl",
    "experiments.jsonl",
    "decisions.jsonl",
    "outcomes.jsonl",
    "audit.jsonl",
)


class StateStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, relative: str) -> Path:
        candidate = (self.root / relative).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise AutopilotError(f"State path escapes state directory: {relative}")
        return candidate

    def initialize(self, seed_dir: Path | None = None) -> None:
        if seed_dir is not None:
            seed_root = seed_dir.resolve()
            if seed_root != self.root:
                for name in _SEED_FILES:
                    source = seed_root / name
                    target = self.path(name)
                    if source.is_file() and not target.exists():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source, target)
        defaults: tuple[tuple[str, BaseModel], ...] = (
            ("state.json", AutopilotState()),
            ("backlog.json", BacklogFile()),
            ("metrics.json", MetricsFile()),
            ("approvals.json", ApprovalsFile()),
            ("risks.json", RisksFile()),
        )
        for name, value in defaults:
            if not self.path(name).exists():
                self.write_model(name, value)
        json_models: tuple[tuple[str, type[BaseModel]], ...] = (
            ("state.json", AutopilotState),
            ("backlog.json", BacklogFile),
            ("metrics.json", MetricsFile),
            ("approvals.json", ApprovalsFile),
            ("risks.json", RisksFile),
        )
        for name, json_model_type in json_models:
            self.read_model(name, json_model_type)
        ledger_models: tuple[tuple[str, type[BaseModel]], ...] = (
            ("observations.jsonl", ObservationLedgerRecord),
            ("experiments.jsonl", ExperimentRecord),
            ("decisions.jsonl", DecisionRecord),
            ("outcomes.jsonl", OutcomeRecord),
        )
        for name, ledger_model_type in ledger_models:
            self.read_jsonl_models(name, ledger_model_type)

    def read_model(self, relative: str, model_type: type[ModelT]) -> ModelT:
        path = self.path(relative)
        try:
            model = model_type.model_validate_json(path.read_text(encoding="utf-8"))
            ensure_safe_payload(model.model_dump(mode="json"), relative)
            return model
        except (OSError, ValueError) as error:
            raise AutopilotError(f"Could not load {relative}: {error}") from error

    def write_model(self, relative: str, model: BaseModel) -> None:
        self.write_json(relative, model.model_dump(mode="json"))

    def write_json(self, relative: str, value: object) -> None:
        ensure_safe_payload(value, relative)
        path = self.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
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

    def append_unique(self, relative: str, record: BaseModel, *, key: str) -> bool:
        path = self.path(relative)
        value = record.model_dump(mode="json")
        ensure_safe_payload(value, relative)
        identity = value.get(key)
        if identity is None:
            raise AutopilotError(f"Append-only record is missing unique key {key}")
        if path.exists():
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    existing = json.loads(line)
                except json.JSONDecodeError as error:
                    raise AutopilotError(
                        f"Invalid JSONL in {relative} at line {line_number}: {error}"
                    ) from error
                if existing.get(key) == identity:
                    if existing != value:
                        raise AutopilotError(
                            f"Conflicting append-only record for {key}={identity} in {relative}"
                        )
                    return False
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            payload = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
                "utf-8"
            )
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return True

    def read_jsonl_models(self, relative: str, model_type: type[ModelT]) -> list[ModelT]:
        path = self.path(relative)
        if not path.exists():
            return []
        records: list[ModelT] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                model = model_type.model_validate_json(line)
                ensure_safe_payload(model.model_dump(mode="json"), relative)
                records.append(model)
            except ValueError as error:
                raise AutopilotError(
                    f"Invalid JSONL in {relative} at line {line_number}: {error}"
                ) from error
        return records

    def merge_cycle_input(self, cycle_input: CycleInput) -> None:
        backlog = self.read_model("backlog.json", BacklogFile)
        candidates = {item.task_id: item for item in backlog.items}
        candidates.update({item.task_id: item for item in cycle_input.candidates})
        self.write_model(
            "backlog.json",
            BacklogFile(items=[candidates[key] for key in sorted(candidates)]),
        )

        metrics = self.read_model("metrics.json", MetricsFile)
        metric_items = {item.metric_id: item for item in metrics.items}
        metric_items.update({item.metric_id: item for item in cycle_input.metrics})
        self.write_model(
            "metrics.json",
            MetricsFile(items=[metric_items[key] for key in sorted(metric_items)]),
        )

        approvals = self.read_model("approvals.json", ApprovalsFile)
        approval_items = {item.approval_id: item for item in approvals.items}
        approval_items.update({item.approval_id: item for item in cycle_input.approvals})
        self.write_model(
            "approvals.json",
            ApprovalsFile(items=[approval_items[key] for key in sorted(approval_items)]),
        )

        for experiment in cycle_input.experiments:
            self.append_unique("experiments.jsonl", experiment, key="experiment_id")
        for outcome in cycle_input.outcomes:
            self.append_unique("outcomes.jsonl", outcome, key="outcome_id")

    def cached_result(self, cycle_id: str) -> CycleOutput | None:
        path = self.path(f"cycles/{cycle_id}/result.json")
        if not path.exists():
            return None
        try:
            return CycleOutput.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise AutopilotError(f"Invalid cached cycle result: {error}") from error

    def write_cycle_result(self, result: CycleOutput) -> None:
        self.write_model(f"cycles/{result.cycle_id}/result.json", result)
