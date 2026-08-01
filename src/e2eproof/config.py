from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .errors import ContractError
from .models import Contract

_LIKELY_SECRET_PATTERNS = [
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?:ghp|github_pat)_[A-Za-z0-9_]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
]


def reject_likely_literal_secrets(text: str) -> None:
    for pattern in _LIKELY_SECRET_PATTERNS:
        if pattern.search(text):
            raise ContractError(
                "Contract appears to contain a literal credential. Use a secrets environment "
                "reference instead of storing credentials in YAML."
            )


SAMPLE_CONTRACT = """version: 1
name: Lead form persists and confirms
description: Verify the visible success message and the actual backend side effect.
base_url: http://127.0.0.1:8765

variables:
  email: test+{{run_id}}@example.com

secrets: {}

browser:
  engine: chromium
  headless: true
  viewport_width: 1280
  viewport_height: 720

policy:
  timeout_ms: 10000
  navigation_timeout_ms: 30000
  retries: 0
  allowed_hosts:
    - 127.0.0.1
    - localhost
  fail_on_console_error: true
  fail_on_page_error: true
  fail_on_request_failure: true
  forbidden_visible_markers:
    - demo mode
    - mock response
    - fallback active

# Evidence is written under evidence/<run-id>/.
evidence:
  output_dir: evidence
  screenshot: failure
  trace: failure
  include_console: true
  include_network: true
  include_response_bodies: false

flows:
  - id: lead-capture
    claim: A submitted lead is persisted exactly once and the user sees a real confirmation.
    steps:
      - type: browser.goto
        url: /app/real

      - type: browser.fill
        target:
          label: Email
        value: "{{email}}"

      - type: browser.click
        target:
          role: button
          name: Submit lead

      - type: browser.assert_text
        target: "#status"
        contains: Saved

      - type: network.assert
        kind: response
        url_contains: /api/leads
        method: POST
        status: 201
        minimum: 1
        maximum: 1

      - type: http.poll
        name: persisted-lead
        method: GET
        url: /api/leads?email={{email}}
        poll_timeout_ms: 5000
        interval_ms: 250
        assertions:
          status: 200
          json:
            - path: $.count
              equals: 1
            - path: $.items[0].email
              equals: "{{email}}"

      - type: browser.audit_accessibility
        maximum_violations: 0
"""


def load_contract(path: str | Path) -> Contract:
    contract_path = Path(path)
    if not contract_path.exists():
        raise ContractError(f"Contract does not exist: {contract_path}")
    if not contract_path.is_file():
        raise ContractError(f"Contract path is not a file: {contract_path}")

    try:
        text = contract_path.read_text(encoding="utf-8")
        reject_likely_literal_secrets(text)
        raw: Any = yaml.safe_load(text)
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ContractError(f"Could not read YAML contract: {error}") from error

    if not isinstance(raw, dict):
        raise ContractError("Contract root must be a YAML mapping")

    try:
        return Contract.model_validate(raw)
    except ValidationError as error:
        messages = []
        for item in error.errors(include_url=False):
            location = ".".join(str(part) for part in item["loc"])
            messages.append(f"- {location}: {item['msg']}")
        raise ContractError("Invalid contract:\n" + "\n".join(messages)) from error


def write_sample_contract(path: str | Path, *, force: bool = False) -> Path:
    output = Path(path)
    if output.exists() and not force:
        raise ContractError(f"Refusing to overwrite existing file: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(SAMPLE_CONTRACT, encoding="utf-8")
    return output
