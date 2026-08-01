# Threat model

## Assets

- test credentials;
- private signing key;
- application data;
- evidence integrity;
- CI runner and developer machine.

## Primary threats and controls

| Threat | Control |
|---|---|
| SSRF or unexpected outbound host | strict scheme/host validation; browser subresource blocking |
| Redirect to an untrusted domain | HTTP redirect following disabled; final browser URL validated |
| Secret written to JSON/logs | environment references plus recursive redaction |
| Secret visible in pixels/trace | secret-bearing runs reject binary evidence unless explicitly opted in |
| Path traversal | all evidence paths resolved beneath the run root |
| Modified evidence | SHA-256 manifest, hash-chained events and optional Ed25519 signature |
| Attacker re-signs with own key | verify against an independently trusted public key |
| Prompt injection from tested app | AI diagnosis treats evidence as untrusted data; AI never determines pass/fail |
| Flaky test hidden by retries | original attempts preserved and flow marked `flaky` |
| False UI success | independent network and backend read-back assertions |

## Residual risk

- A compromised test API can lie consistently to both application and verifier.
- DNS rebinding and local network policy require environment-specific hardening.
- Screenshots can contain personal data even without configured secrets.
- The baseline accessibility audit is not equivalent to expert WCAG testing.
- A passing contract covers only the configured claims, environment and data.
