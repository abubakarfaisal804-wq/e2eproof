# Autopilot dry-run operations

## Local deterministic run

Use an isolated writable state and output directory. The fake mode is the only v1
mode and has a model-call budget of zero.

```bash
e2eproof autopilot dry-run \
  --input evals/autopilot/fixtures/local-cycle.json \
  --repository-root . \
  --seed-dir ops \
  --state-dir autopilot-state \
  --output autopilot-output/result.json \
  --brief autopilot-output/execution-brief.json \
  --summary autopilot-output/summary.md
```

The command exits `0` for a selected brief or a legitimate no-action cycle and `2`
when fail-closed observation policy blocks planning. Reusing the same cycle ID returns
the cached result without appending duplicate records. Reusing a cycle ID with changed
structured input fails instead of silently returning or overwriting a different cycle.

## Live read-only GitHub observation

Set `GITHUB_TOKEN` in the environment; never pass it on the command line or store it in
input. The token needs read access only.

```bash
e2eproof autopilot dry-run \
  --input evals/autopilot/fixtures/local-cycle.json \
  --github-live \
  --github-repository abubakarfaisal804-wq/e2eproof
```

The observer reads repository metadata, branches, open pull requests, recent Actions
runs, aggregate security endpoint status, and releases. It does not read PR comments,
issue bodies, email, or customer systems.

## Scheduled workflow

`.github/workflows/autopilot.yml` runs hourly and by `workflow_dispatch`. Its explicit
permissions are read-only. It restores the latest default-branch state cache, runs one
cycle, saves state only after success, and uploads JSON, Markdown, and state as a
14-day artifact. The workflow contains no push, PR, release, deployment, or messaging
step.

## Recovery and audit

- A current `.autopilot.lock` causes a bounded failure instead of concurrent writes.
- A stale lock is recovered and recorded.
- An interrupted `active_cycle` marker is recorded on the next run; its input digest
  prevents reuse with changed input, and partial observations are reused.
- Atomic JSON replacement prevents partially written snapshots.
- JSONL records use stable IDs, skip identical duplicates, and reject conflicting IDs.
- `audit.jsonl` is append-only and hash-linked; a verification failure stops the run.

After an interruption, rerun with the same cycle ID first. If state validation still
fails, preserve the directory as evidence and start from a reviewed copy of the last
successful artifact. Do not delete or edit individual audit lines.

## Input updates

Metrics, experiments, outcomes, and approvals must be structured and attributable.
Mark each measurement as verified, estimated, or hypothetical. A completed outcome for
the active task frees the single planning slot. Owner approvals must be task-scoped and
include scope, decision, actor, time, expiry when applicable, and an evidence note.
