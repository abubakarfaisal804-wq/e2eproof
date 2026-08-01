# Architecture

## Trust boundaries

1. **Contract** — user-controlled YAML, validated with a strict schema.
2. **Application under test** — fully untrusted browser/API content.
3. **Runner** — deterministic authority for pass/fail.
4. **Optional AI** — advisory only; cannot mark a run as passed.
5. **Evidence directory** — local append/write target with path traversal protection.
6. **Signing key** — external secret that should never be committed or uploaded.

## Execution path

```text
YAML contract
   ↓ strict validation + URL policy
isolated browser context + HTTP client
   ↓
step executor
   ├─ UI assertion
   ├─ network assertion
   ├─ independent HTTP read-back
   └─ policy gates
   ↓
structured result
   ├─ report.html
   ├─ result.json
   ├─ junit.xml
   ├─ console/network evidence
   ├─ optional screenshots/trace
   ├─ hash-chained events.jsonl
   └─ manifest + optional Ed25519 signature
```

## Design rules

- A model response is data, not authority.
- UI success alone is weak evidence.
- Every material side effect should have an independent read-back.
- Retries classify a flow as flaky; they do not erase the original failure.
- Unexpected hosts and redirects fail closed.
- Text evidence is redacted before writing.
- Binary evidence with secrets requires explicit risk acceptance.
