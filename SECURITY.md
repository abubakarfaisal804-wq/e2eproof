# Security policy

## Reporting

Do not publish suspected vulnerabilities with real credentials or customer data. Create a private security advisory in the project repository when available.

## Credential handling

- Never place API keys directly in contracts.
- Use `secrets` with environment variables.
- Never commit `.e2eproof-keys`, `.env`, evidence bundles or browser storage state.
- Use dedicated test accounts with minimum permissions.
- Keep signing private keys outside the repository.

## Sensitive artifacts

Text and JSON evidence is redacted. Screenshots and Playwright traces are binary and can contain passwords, tokens, personal information or customer data. E2EProof rejects binary artifacts when configured secrets are present unless `allow_sensitive_artifacts: true` is explicitly set.

## Supported versions

Only the newest minor version receives security fixes during this pre-1.0 phase.
