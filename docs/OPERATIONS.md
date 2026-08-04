# Engineering operations

## Safe change cycle

1. Start from current `origin/main`; inspect open PRs and branches before creating
   work.
2. Use one dedicated branch or worktree. Never edit protected `main` directly.
3. Implement one smallest complete change and its tests.
4. Inspect the full diff for secrets, unsupported claims, destructive behavior, and
   unrelated files.
5. Push only after local checks pass; record genuine limitations in the PR.
6. Merge only with every required check green, no unresolved review conversation, and
   a low-risk reversible diff.

## Local validation

Use a supported Python (3.11–3.13) in an isolated virtual environment:

```bash
python -m pip install --upgrade pip setuptools wheel
python -m pip install --no-build-isolation -e ".[dev]"
python -m compileall -q src tests demo scripts
python -m ruff check .
python -m ruff format --check .
python -m mypy src/e2eproof
python scripts/static_audit.py
python -m pytest -m "not browser and not integration" -q
python -m pytest --cov=e2eproof --cov-report=term-missing
python -m build
python -m twine check dist/*
python -m pip check
python -m pip install pip-audit
python -m pip_audit
```

Install the selected Playwright browser before browser-marked tests. Platform-specific
local failures must be reported separately from product regressions.

## Release boundary

Automation may prepare artifacts and evidence but must not publish a production release,
change credentials, pricing, billing, legal terms, or production data. The owner must
approve and perform those actions using the account controls in `RELEASE_SETUP.md`.

## Scheduled local operator

An hourly local Codex automation requires the computer to remain awake, online, and the
Codex app available. Each run must return evidence to the review queue and stop for any
action that crosses the release, credential, billing, legal, production-data, or
irreversible-migration boundary.
