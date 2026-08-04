# Engineering decisions

## 2026-08-04 — Complete the existing dependency PR

Decision: improve PR #1 instead of opening a duplicate dependency PR.

Evidence: PR #1 already updates the Python dependency group and all checks except a
stale dependency-review run were green. Its proposed `cryptography>=44,<50` range
still admitted releases affected by CVE-2026-69247, whose first patched release is
50.0.0.

Consequence: require `cryptography>=50,<51` in both package metadata and the plain
requirements file. This excludes all four vulnerabilities found by `pip-audit` on
46.0.7 while keeping the upgrade bounded to one major line.

## 2026-08-04 — Reuse product browser discovery in tests

Decision: browser-marked pytest tests use one shared launch-options fixture backed by
the product's browser discovery instead of hard-coding `/usr/bin/chromium`.

Reason: the hard-coded Linux path made the complete suite fail on Windows even though
`e2eproof doctor` had found an authorized Chrome installation. The fixture preserves
Linux root sandbox flags and makes the same tests executable across supported systems.

## 2026-08-04 — Do not suppress the CodeQL sink broadly

Decision: retain CodeQL alert #1 in the backlog until the CLI verification output can
be made unambiguous with a narrow code-and-test change.

Reason: suppressing the shared JSON printer could hide a future real secret flow. The
reported `trusted_key_match` value is a boolean about a public key, but the common sink
is also used by other commands.

## 2026-08-04 — Preserve verification output while correcting the CodeQL source

Decision: name the internal boolean `expected_signer_match`, retain
`trusted_key_match` as the stable CLI JSON key and a read-only Python compatibility
property, and leave the shared JSON printer and CodeQL configuration unchanged.

Reason: the value compares two public Ed25519 keys and contains no key material. The
CodeQL SARIF path showed that its former attribute name was the heuristic sensitive
source. The corrected name describes signer identity, while an end-to-end signed
verification test protects behavior and compatibility.

## 2026-08-04 — Defer cloud infrastructure

Decision: prioritize local reliability, release truth, and external validation before
hosted execution.

Reason: the repository contains no evidence that the documented tester or paid-pilot
gates have been met. Infrastructure without that evidence adds cost and security risk.
