# Autonomous engineering backlog

Last verified: 2026-08-04. Items are ordered by evidence, user impact, urgency,
effort, and reversibility. Completed work remains in Git history rather than this
active list.

## P0 — Reliability and trust

- Resolve CodeQL alert #1 without weakening scanning. The current trace treats the
  `trusted_key_match` verification boolean as sensitive data flowing to CLI JSON.
- Enable Dependabot alerts in repository settings. On 2026-08-04 the API reported
  Dependabot alerts and security updates disabled; secret scanning and push
  protection were enabled.
- Add a recurring dependency audit that detects vulnerable versions already present
  on `main`; dependency review alone evaluates changes introduced by a PR.

## P1 — Reproducible development and release health

- Remove the strict-mypy quarantine for `e2eproof.cli` and `e2eproof.runner` one
  module at a time, with no loss of runtime coverage.
- Reconcile `RELEASE_STATUS_NL.md` and release instructions with the public
  repository and the actual v0.2.0 prerelease state.
- Verify clean installation from the public package index before claiming PyPI
  availability. Do not publish a release automatically.

## P2 — Distribution evidence

- Run the documented five-tester onboarding experiment and record only observed
  completion, defects found, retention, and paid intent.
- Publish reproducible case studies for fake success, duplicate side effects, and
  silent fallbacks after the underlying examples pass in CI.

## Deferred — Cloud product

- Start a hosted vertical slice only after the validation gates in
  `docs/BUSINESS_VALIDATION.md` have evidence. Authentication, isolation, evidence
  retention, audit logs, usage limits, recovery, and entitlements require a threat
  model before implementation.
