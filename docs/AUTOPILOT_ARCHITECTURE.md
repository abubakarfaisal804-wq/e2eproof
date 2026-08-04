# Autopilot dry-run architecture

Autopilot v1 is a coordination layer, not an executor. It turns structured facts,
estimates, hypotheses, persistent state, and a bounded read-only GitHub snapshot into
at most one execution brief. It cannot modify source, open or merge a pull request,
send a message, deploy, publish, change credentials, spend money, or make a legal
commitment.

## Data flow

```text
structured JSON + local git + read-only GitHub GETs
                         |
                         v
       validated observations and state ledgers
                         |
                         v
 duplicate/staleness gates -> deterministic integer scoring
                         |
                         v
             policy and owner-approval gate
                         |
                         v
       one dry-run execution brief or no action
                         |
                         v
 atomic state + append-only audit + JSON/Markdown artifact
```

The implementation follows the existing `src/e2eproof` package convention under
`src/e2eproof/autopilot`. The checked-in `ops` directory is seed state. Local or CI
runs copy that seed into a writable state directory; GitHub Actions persists the
writable directory through a default-branch-scoped cache and uploads it as a readable
artifact. No workflow commits state to the repository.

## Trust boundaries

1. Structured input is untrusted until Pydantic validation and persistent-state
   content checks pass.
2. Local Git is observed only with read-only commands and a process timeout.
3. The GitHub observer uses fixed GET endpoints, no redirects, a request budget,
   bounded retries, and a per-request timeout. Tokens exist only in request headers.
4. The fake planner is deterministic. It makes no network or model call and stores no
   prompts, model output, reasoning traces, or chain of thought.
5. Policy is authoritative over the candidate. A score can never enable a prohibited
   action.
6. State writes are confined to the selected state directory and use atomic replace;
   JSONL ledgers and audit events are append-only.

## State and recovery

`state.json` holds the revision, interrupted-cycle marker, active task, completed
cycle IDs, and recommendation cooldowns. Backlog, metrics, approvals, and risks use
versioned JSON envelopes. Observations, decisions, experiments, and outcomes use
versioned JSONL records. `audit.jsonl` links each event to the preceding event hash.

A cross-platform exclusive lock prevents concurrent writers. A bounded stale-lock
recovery records what happened. The controller writes an active-cycle marker before
observation; the marker binds the cycle ID to its structured-input digest. A retry
reuses any observations that the interrupted cycle already appended and rejects
changed input under the same ID. A stable cycle ID and cached cycle result make
completed retries idempotent.

## Planning contract

Every score component has a value from 0 through 5, a basis (`verified`, `estimate`,
or `hypothesis`), evidence references, and a short note. Integer weights are fixed in
`scoring.py`. Tie-breaking is deterministic. A candidate is ineligible when it lacks
verified evidence, has a task ID with a completed outcome, duplicates another queued
objective, is inside an unchanged-evidence cooldown, or requests a permanently
blocked history rewrite.

An existing active task owns the single execution slot. Autopilot does not emit a
second recommendation until a structured terminal outcome clears that slot.

## Schemas

Committed input, output, and brief schemas live in `docs/schemas`. Regenerate them
with:

```bash
e2eproof autopilot schemas --output-dir docs/schemas
```
