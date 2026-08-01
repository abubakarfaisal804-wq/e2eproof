from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


Status = Literal["passed", "failed", "skipped", "flaky"]


class ResultModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StepResult(ResultModel):
    index: int
    id: str
    type: str
    status: Status
    started_at: str
    finished_at: str
    duration_ms: int = Field(ge=0)
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)
    attempt: int = Field(default=1, ge=1)


class FlowAttempt(ResultModel):
    attempt: int = Field(ge=1)
    status: Literal["passed", "failed"]
    started_at: str
    finished_at: str
    duration_ms: int = Field(ge=0)
    steps: list[StepResult]
    failure: str | None = None


class FlowResult(ResultModel):
    id: str
    claim: str
    status: Status
    started_at: str
    finished_at: str
    duration_ms: int = Field(ge=0)
    attempts: list[FlowAttempt]
    tags: list[str] = Field(default_factory=list)


class RunResult(ResultModel):
    schema_version: int = 1
    product: str = "E2EProof"
    product_version: str
    run_id: str
    contract_name: str
    contract_path: str
    contract_sha256: str
    status: Status
    started_at: str
    finished_at: str
    duration_ms: int = Field(ge=0)
    environment: dict[str, Any]
    flows: list[FlowResult]
    summary: dict[str, int]
    policy_findings: list[str] = Field(default_factory=list)
    integrity: dict[str, Any] = Field(default_factory=dict)
