# Changelog

## 0.2.0 — 2026-08-01

### Added
- `e2eproof quickstart` for a real local browser-to-backend proof.
- `e2eproof demo` and `e2eproof install-browser` commands.
- Chromium, Firefox, and WebKit overrides for CLI and GitHub Action.
- Browser-aware doctor checks.
- Packaged local demo server so quickstart works from an installed wheel.
- GitHub CI definitions for three operating systems, three Python versions, and a 3×3 browser matrix.
- GitHub Action self-test, CodeQL, dependency review, Dependabot, release attestations, and PyPI Trusted Publishing workflows.
- Public release configuration and GitHub publication scripts.
- Contribution, support, issue, release, and branch-protection templates.
- `py.typed` marker.

### Changed
- GitHub Action now sets up Python itself and supports configurable evidence artifacts.
- Browser launch hints now name the selected browser.
- Windows and Unix start scripts use the installed CLI demo.

### Fixed
- Packaged demo write IDs are now assigned under the store lock.
- Chromium-only `--no-sandbox` argument is no longer passed to Firefox or WebKit.

## 0.1.0 — 2026-08-01

- Initial local-first contract runner.
- Browser, network, and HTTP verification.
- Evidence bundles, hash chain, signatures, HTML/JSON/JUnit output.
- Deterministic mock/fallback, duplicate-write, console, accessibility, and flaky-flow examples.
