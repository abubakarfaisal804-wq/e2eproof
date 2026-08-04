# Cloud roadmap

E2EProof is currently a local CLI and GitHub Action. This roadmap is conditional;
it is not a claim that hosted capabilities, customers, or revenue exist.

## 1. Reliability and trust

- Keep required CI green across Python 3.11–3.13 and supported browsers.
- Eliminate known vulnerable dependencies and unresolved high-severity scanning
  alerts.
- Prove clean package and Action installation from released artifacts.
- Keep security, release, and onboarding documentation aligned with reality.

Exit evidence: clean security checks, reproducible installs, green protected-branch
checks, and no unsupported release claims.

## 2. Distribution and validation

- Reduce time to first evidence report through the quickstart and diagnostics.
- Recruit testers using the existing alpha guide and issue template.
- Measure completed first runs, real defects found, repeat use, and paid intent.

Exit evidence: the validation gates in `docs/BUSINESS_VALIDATION.md` are met with
traceable, non-fabricated observations.

## 3. Minimal hosted vertical slice

- Define organizations, authentication, repository authorization, and tenancy.
- Execute one queued job in an isolated, least-privilege environment.
- Store encrypted evidence with explicit retention and deletion controls.
- Expose run history, status, audit events, usage limits, and recovery procedures.

Exit evidence: a threat-reviewed pilot can connect one repository, run one contract,
retrieve evidence, and revoke access without cross-tenant leakage.

## 4. Revenue and scale

- Add entitlements before billing integration.
- Offer self-service onboarding only after support and recovery paths are proven.
- Scale infrastructure from measured pilot load, not forecasts.

Production infrastructure, pricing, billing, legal terms, and releases always require
an explicit owner action.
