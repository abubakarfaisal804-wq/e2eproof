# E2EProof alpha test — 15-minute guide

Thank you for testing E2EProof. This is an alpha usability test, not a sales call.

## Safety

- Use only a local, test, or staging application you own or are authorized to test.
- Never post production credentials, cookies, private customer data, private URLs, or unredacted traces.
- Stop immediately when you are not authorized to test the target.

## A. Baseline quickstart

Record the start time, then run:

```bash
python -m pip install --upgrade e2eproof
e2eproof quickstart
```

Record your operating system, Python version, minutes to first evidence report,
anything confusing, and the exact error when it fails.

## B. Your own application

Choose one non-production flow with a real side effect, for example:

- a form creates exactly one record;
- a test checkout creates exactly one test payment;
- a webhook is received exactly once;
- an account change is persisted;
- an AI provider responds without a mock or fallback.

Create and validate a starter contract:

```bash
e2eproof init e2eproof.yaml
e2eproof validate e2eproof.yaml
```

Edit it for your local or staging app, then run:

```bash
e2eproof run e2eproof.yaml
```

## C. Report the result

Open an **Alpha test report** issue in the repository.

A failed test is valuable evidence. We need to learn whether you could reach a
report within 15 minutes, verify one real outcome, catch a meaningful issue,
and whether you would use E2EProof again.
