# Release test matrix

## Required before v0.2.0 public release

| Area | Matrix | Gate |
|---|---|---|
| Unit behavior | Ubuntu/Windows/macOS × Python 3.11/3.12/3.13 | All pass |
| Real navigation | Ubuntu/Windows/macOS × Chromium/Firefox/WebKit | All 9 pass |
| Static | Ruff, strict mypy, compileall, custom audit | All pass |
| Packaging | wheel + sdist + metadata check + clean install | All pass |
| GitHub Action | local composite-action self-test | Pass |
| Security | CodeQL + dependency review + secret/static audit | No blocking finding |
| Evidence | positive, negative, tamper, signature, path and redaction tests | All pass |

## Negative scenarios included

- visible fake success without backend write;
- duplicate backend writes;
- hidden provider fallback;
- console and page errors;
- failed network request;
- wrong backend count;
- flaky first attempt;
- baseline accessibility failure;
- evidence manipulation;
- path traversal and host confusion;
- literal credential detection and redaction behavior.

A green matrix only proves the defined scenarios and environments. It never proves every possible application.
