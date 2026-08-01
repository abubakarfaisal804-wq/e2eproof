# Contract reference

## Top-level fields

- `version`: currently `1`.
- `name`: report name.
- `base_url`: application/API root.
- `variables`: reusable values; `{{run_id}}`, `{{timestamp}}`, and `{{date}}` are built in.
- `secrets`: environment references, never literal secret values.
- `browser`: engine, viewport, locale, timezone and TLS settings.
- `policy`: timeout, retries, allowlists and error gates.
- `evidence`: artifact behavior and optional signing key.
- `flows`: outcome claims and ordered steps.

## Locator priority

Prefer stable accessible locators:

```yaml
target: {role: button, name: Submit}
target: {label: Email}
target: {test_id: checkout-submit}
```

CSS is supported but generally more fragile.

## Browser steps

- `browser.goto`
- `browser.fill`
- `browser.click`
- `browser.press`
- `browser.select`
- `browser.check`
- `browser.wait`
- `browser.assert_text`
- `browser.assert_visible`
- `browser.assert_url`
- `browser.assert_value`
- `browser.assert_count`
- `browser.screenshot`
- `browser.extract`
- `browser.audit_accessibility`
- `browser.assert_performance`

## Network and API steps

- `network.assert`: exact counts and filters over captured browser traffic.
- `http.request`: deterministic HTTP assertion.
- `http.poll`: repeat a read-back until it matches or times out.
- `set.variable`: add a runtime value.

## JSON paths

The deliberately small implementation supports deterministic paths such as:

- `$`
- `$.count`
- `$.items[0].email`

Wildcards, filters and arbitrary expressions are intentionally unsupported.

## Secret example

```yaml
secrets:
  admin_token:
    env: TEST_ADMIN_TOKEN
    required: true

flows:
  - id: read-back
    claim: The record can be read through the test API.
    steps:
      - type: http.request
        url: /api/test/record
        headers:
          Authorization: Bearer {{secret.admin_token}}
```

When secrets exist, set screenshots and traces to `never`, unless you explicitly accept binary-artifact leakage risk:

```yaml
evidence:
  screenshot: never
  trace: never
```
