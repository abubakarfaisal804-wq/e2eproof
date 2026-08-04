# Known risks

Last verified: 2026-08-04.

| Risk | Evidence | Current control | Next action |
|---|---|---|---|
| Existing v0.2.0 installs may retain vulnerable cryptography versions | `pip-audit` found one high GHSA and three 2026 CVEs in installed 46.0.7 | Source metadata now requires `cryptography>=50,<51`; a clean local audit was recorded | Publish only through an owner-approved security release and tell existing users to upgrade |
| Dependabot alerts disabled | Repository API returned alerts and security updates disabled | Dependency review workflow and local `pip-audit` | Owner enables Dependabot alerts in repository settings |
| Partial strict typing | `cli` and `runner` are excluded by a mypy override | Strict mypy remains active elsewhere | Remove exclusions incrementally with tests |
| Release documentation drift | `RELEASE_STATUS_NL.md` still says no public repository | GitHub release v0.2.0 exists as a prerelease | Re-audit PyPI and Marketplace state, then correct claims |
| Sensitive binary evidence | Screenshots and traces can contain secrets or personal data | Secret-bearing runs fail closed unless explicitly opted in | Add hosted retention and access design before cloud storage |
| Autopilot priority or state error | Structured inputs can be stale, incomplete, or wrong even when schema-valid | Verified/estimate/hypothesis labels, one active slot, cooldowns, fail-closed observation gates, dry-run-only policy | Review scheduled artifacts and evaluation evidence before designing any execution handoff |

Residual product risks in `docs/THREAT_MODEL.md` remain applicable.
