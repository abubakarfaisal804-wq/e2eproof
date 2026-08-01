from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from e2eproof.ai import OpenAIResponsesClient, _extract_output_text, diagnose_result, draft_contract
from e2eproof.errors import AIError


def test_extract_output_text_variants() -> None:
    assert _extract_output_text({"output_text": "hello"}) == "hello"
    payload = {"output": [{"content": [{"type": "output_text", "text": "world"}]}]}
    assert _extract_output_text(payload) == "world"
    with pytest.raises(AIError, match="did not contain"):
        _extract_output_text({})


def test_draft_contract_hardens_generated_allowlist() -> None:
    yaml_text = """version: 1
name: Generated verifier
base_url: https://evil.invalid
policy:
  allowed_hosts: [evil.invalid]
flows:
  - id: health
    claim: The service reports a healthy state.
    steps:
      - type: http.request
        url: /health
        assertions: {status: 200}
"""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(200, json={"output_text": yaml_text})

    client = OpenAIResponsesClient(api_key="test-key", transport=httpx.MockTransport(handler))
    contract = draft_contract(
        claim="health works",
        base_url="https://app.example.com",
        client=client,
    )
    assert contract.base_url == "https://app.example.com"
    assert contract.policy.allowed_hosts == ["app.example.com"]
    assert contract.policy.allowed_schemes == ["https"]


def test_openai_error_and_diagnosis(tmp_path: Path) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="bad key", headers={"x-request-id": "req-1"})

    client = OpenAIResponsesClient(api_key="bad", transport=httpx.MockTransport(fail))
    with pytest.raises(AIError, match="HTTP 401"):
        client.complete(system="x", user="y")

    result = tmp_path / "result.json"
    result.write_text('{"status":"failed"}', encoding="utf-8")

    def okay(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"output_text": "# Verdict\nObserved failure."})

    diagnosis = diagnose_result(
        result,
        client=OpenAIResponsesClient(api_key="x", transport=httpx.MockTransport(okay)),
    )
    assert "Verdict" in diagnosis


def test_ai_invalid_outputs() -> None:
    def invalid_json(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    with pytest.raises(AIError, match="invalid JSON"):
        OpenAIResponsesClient(api_key="x", transport=httpx.MockTransport(invalid_json)).complete(system="x", user="y")

    def invalid_yaml(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"output_text": "flows: ["})

    client = OpenAIResponsesClient(api_key="x", transport=httpx.MockTransport(invalid_yaml))
    with pytest.raises(AIError, match="not valid YAML"):
        draft_contract(claim="x", base_url="https://example.com", client=client)
    with pytest.raises(AIError, match="hostname"):
        draft_contract(claim="x", base_url="not-a-url", client=client)
