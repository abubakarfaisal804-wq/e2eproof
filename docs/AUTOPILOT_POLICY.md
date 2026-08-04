# Autopilot dry-run policy

## Non-negotiable v1 boundary

Autopilot v1 may observe, score, persist state, run read-only checks, and generate a
brief. It has no executor and all of these actions remain prohibited in every output:

- application-code changes and pull-request creation or merge;
- email or other outbound messages;
- deployments and releases;
- credential or secret changes;
- spending or paid infrastructure;
- pricing, billing, legal, or contractual changes;
- customer production-data access;
- destructive migrations;
- branch-protection or security-control changes;
- force pushes and protected-history rewrites.

An approval record documents owner intent; it does not grant execution capability to
this version.

## Approval rules

Spending, paid infrastructure, credentials, secrets, pricing, billing, legal changes,
customer production data, releases, deployments, destructive migrations, branch
protection, and security controls require a current task-scoped owner approval before
a brief can say that its policy scope is satisfied. Missing or expired scopes are
listed explicitly.

Force pushes and protected-history rewrites are hard-blocked. An approval cannot
override that block in v1.

## Data minimization

Persistent input rejects likely literal credentials and fields commonly used for
complete email bodies, raw messages, prompts, model responses, chain of thought, or
reasoning traces. Store a short factual summary and evidence reference instead. Do not
put tokens, cookies, customer records, unredacted traces, or complete personal email
bodies in observations or metrics.

## Fail-closed conditions

No task is selected when a required verified observation category is missing, a live
critical observation fails, the API budget is exhausted, state cannot be validated,
the audit chain fails, or another process holds a current lock. Errors never trigger a
fallback model or an external action.
