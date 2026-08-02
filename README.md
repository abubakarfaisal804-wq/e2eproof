# E2EProof

**Verify what an application actually did — not only what its interface claimed.**

E2EProof is a local-first command-line tool and GitHub Action for AI-built web apps and automations. A YAML contract describes a promised outcome such as:

> Submitting this form stores exactly one lead and then shows a confirmation.

E2EProof executes the user flow, checks independent side effects, and writes a tamper-evident evidence bundle with an HTML report, JSON result, JUnit XML, optional browser traces/screenshots, a SHA-256 manifest, and a hash-chained event log.

## Two-command proof

Install from PyPI:

```bash
python -m pip install e2eproof
e2eproof quickstart
```

`quickstart` checks for Chromium, asks permission to install it when missing, starts a real local web app, submits a form in a real browser, reads the backend independently, and opens the report.

Non-interactive CI:

```bash
e2eproof quickstart --yes --no-open --json
```

Other browsers:

```bash
e2eproof quickstart --browser firefox
e2eproof quickstart --browser webkit
```

## Verify your own app

```bash
e2eproof init e2eproof.yaml
e2eproof validate e2eproof.yaml
e2eproof run e2eproof.yaml
```

A strong contract combines independent observations:

1. perform the user action;
2. assert what the user sees;
3. assert the exact network request and response;
4. read the real backend state through a second interface;
5. fail when the result is absent, duplicated, mocked, or silently handled by a fallback.

## GitHub Action

Add the published Action to your workflow:

```yaml
name: outcome proof
on: [push, pull_request]

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: abubakarfaisal804-wq/e2eproof@v0.2.0
        with:
          contract: e2eproof.yaml
          browser: chromium
```

The action installs Python and the selected browser, runs the contract, uploads the evidence bundle, and fails the job when a required claim fails.

## Contract example

```yaml
version: 1
name: Lead is stored exactly once
base_url: https://staging.example.com
variables:
  email: test+{{run_id}}@example.com
policy:
  allowed_hosts: [staging.example.com]
  fail_on_console_error: true
  fail_on_page_error: true
  fail_on_request_failure: true
  forbidden_visible_markers: [demo mode, fallback active]
flows:
  - id: lead-capture
    claim: The submitted lead is stored exactly once.
    steps:
      - type: browser.goto
        url: /contact
      - type: browser.fill
        target: {label: Email}
        value: "{{email}}"
      - type: browser.click
        target: {role: button, name: Send}
      - type: browser.assert_text
        target: "#status"
        contains: Received
      - type: network.assert
        kind: response
        url_contains: /api/leads
        method: POST
        status: 201
        minimum: 1
        maximum: 1
      - type: http.poll
        method: GET
        url: /api/test/leads?email={{email}}
        assertions:
          status: 200
          json:
            - {path: $.count, equals: 1}
```

## Commands

```text
e2eproof quickstart                 install/check Chromium and run a real proof
e2eproof demo --browser firefox     run the packaged demo without installation logic
e2eproof install-browser webkit     install a Playwright browser
e2eproof doctor --browser chromium  check prerequisites
e2eproof init                       create a conservative starter contract
e2eproof validate                   validate a contract without executing it
e2eproof run                        execute a contract
e2eproof verify                     verify evidence hashes, chain, and signature
e2eproof keygen                     create an Ed25519 keypair
e2eproof schema                     export the contract JSON Schema
e2eproof ai-draft                   optionally draft a contract with OpenAI
e2eproof ai-diagnose                optionally explain a redacted failure with OpenAI
```

Exit codes:

- `0`: all required claims passed;
- `1`: a claim failed or was flaky under a fail-on-flaky policy;
- `2`: configuration, runtime, or API error;
- `3`: evidence integrity verification failed.

## Evidence integrity

```bash
e2eproof keygen .e2eproof-keys
e2eproof run e2eproof.yaml --sign-key .e2eproof-keys/e2eproof-private.pem
e2eproof verify evidence/<run-id> --public-key .e2eproof-keys/e2eproof-public.pem
```

A signature only establishes identity when the public key is obtained through an independent trusted channel.

## Optional GPT-5.6 Sol integration

The deterministic runner works without AI. GPT-5.6 Sol is optional for drafting conservative contracts and diagnosing redacted failures:

```bash
export OPENAI_API_KEY="sk-proj-..."
e2eproof ai-draft \
  --base-url https://staging.example.com \
  --claim "Submitting checkout creates one paid order" \
  --output checkout.yaml

e2eproof ai-diagnose evidence/<run-id>/result.json --output diagnosis.md
```

Generated contracts are validated before being written. AI output never decides whether a test passed.

## Security defaults

- browser and HTTP targets are scheme/host allowlisted;
- HTTP redirects are not followed automatically;
- browser requests outside the allowlist are blocked by default;
- credentials embedded in URLs are rejected;
- environment secrets are redacted from text and JSON artifacts;
- screenshots and traces are disabled for secret-bearing runs unless explicitly enabled;
- evidence paths cannot escape the run directory;
- signatures use Ed25519 and listed artifacts use SHA-256.

Read `SECURITY.md` and `docs/THREAT_MODEL.md` before using production credentials.

## Development

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install --no-build-isolation -e ".[dev]"
e2eproof install-browser chromium
python -m pytest --cov=e2eproof --cov-report=term-missing
python -m ruff check .
python -m mypy src/e2eproof
```

Public CI covers Python 3.11–3.13 on Ubuntu, Windows, and macOS, plus Chromium, Firefox, and WebKit browser-to-backend proofs. Check the Actions page for the current status before relying on a platform-support claim.

## Current status

E2EProof is an alpha developer tool, not a hosted SaaS and not a guarantee for every application. It requires an explicit contract and does not replace a complete security audit, accessibility audit, or human review.

## License

MIT. See `LICENSE`.
