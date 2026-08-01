# E2EProof v0.2.0 local release-candidate test report

**Date:** 2026-08-01
**Environment:** Linux, Python 3.13.5
**Scope:** local container validation before public GitHub CI

## Passed locally

- Python compileall: passed
- Static audit: 0 errors, 0 warnings across 30 Python files
- Contract validation: 9/9 shipped example contracts valid
- Automated tests: 53 passed
- Branch-aware coverage: 85.24% (minimum 85%)
- Wheel build: passed
- Source distribution build: passed
- Wheel install/import/version smoke test: passed
- Source distribution install/import/version smoke test: passed
- Installed CLI `--version`, `init`, `validate`, and `doctor`: passed
- No literal private key or real API key intentionally included

## Environment-limited test

One real Chromium-to-localhost test was skipped after the browser returned `ERR_BLOCKED_BY_ADMINISTRATOR`. The same runner had already produced a valid evidence bundle proving that the failure was visible rather than silently hidden.

This is a restriction of the managed execution environment. It is **not** counted as a successful navigation test. The public GitHub browser matrix must run successfully before Windows/macOS/Linux and Chromium/Firefox/WebKit support may be claimed as proven.

## Prepared public CI

- Python 3.11, 3.12, 3.13
- Ubuntu, Windows, macOS
- Chromium, Firefox, WebKit real browser-to-backend demo
- GitHub composite Action self-test
- Wheel/source build and clean install
- Ruff, mypy, CodeQL, dependency review
- PyPI Trusted Publishing
- GitHub artifact attestations

These are configurations, not completed public results.

## Known limits

- No public GitHub run yet
- No PyPI/TestPyPI upload yet
- No GitHub Marketplace listing yet
- No external user activation test yet
- No external security audit yet
- No claim of support for every web app or authentication pattern
