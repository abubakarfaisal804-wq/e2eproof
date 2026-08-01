# Contributing

E2EProof accepts focused bug fixes, documentation improvements, adapters, and deterministic verification features.

## Local checks

```bash
python -m pip install --no-build-isolation -e ".[dev]"
e2eproof install-browser chromium
python scripts/release_check.py
python -m ruff check .
python -m mypy src/e2eproof
```

## Pull requests

- Add or update tests for behavior changes.
- Do not weaken host allowlists, credential redaction, path confinement, or deterministic PASS/FAIL rules.
- Do not add silent fallbacks.
- Describe what was tested and what remains untested.
- Keep unrelated changes in separate pull requests.

Security vulnerabilities must be reported privately according to `SECURITY.md`, not through a public issue.
