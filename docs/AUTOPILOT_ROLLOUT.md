# Autopilot rollout

Autopilot remains dry-run until observed evidence supports a narrower next phase. No
date or cycle count alone authorizes execution.

## Phase 0 - local evaluation

- Exercise deterministic selection, ties, duplicates, cooldowns, active tasks,
  approvals, hard blocks, malformed state, lock contention, and interrupted recovery.
- Require schema, unit, coverage, Ruff, strict mypy, static audit, package, and
  dependency checks.
- Inspect every generated brief for unsupported facts and unsafe permissions.

Exit evidence: all evaluation cases pass and repeated identical cycle IDs are
idempotent.

## Phase 1 - scheduled dry-run

- Run the read-only workflow hourly.
- Compare selected tasks against verified repository and business observations.
- Record false priorities, missing observations, stale repetitions, operator edits,
  and approval-gate behavior.
- Keep state in cache/artifacts; do not commit automated decisions to `main`.

Exit evidence: a reviewed sample of cycles is deterministic, non-duplicative,
fail-closed, and useful. The sample size and acceptance threshold must be chosen and
recorded before evaluation; this document does not invent one.

## Phase 2 - bounded handoff design

Only after Phase 1 evidence, design a separate human-reviewed handoff that can enqueue
one brief. Threat-model authentication, authorization, replay protection, audit
retention, and revocation first. Do not add code mutation, PR creation, outreach,
deployment, release, billing, or customer-data access as part of that design by
default.

## Rollback

Disable the schedule through a reviewed pull request, preserve the last artifacts and
audit chain, and diagnose the smallest violated invariant. Do not delete history or
silently reset state.
