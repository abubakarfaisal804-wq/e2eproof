from __future__ import annotations

import httpx
import pytest

from e2eproof.errors import StepExecutionError
from e2eproof.models import HttpAssertions, JsonAssertion, NetworkAssertStep
from e2eproof.runner import NetworkRecord, RuntimeState, _assert_http, _assert_json, _network_assert


def response(status: int = 200, body: str = '{"name":"alpha","items":[1,2]}', headers=None) -> httpx.Response:
    return httpx.Response(status, text=body, headers=headers or {"x-mode": "real"}, request=httpx.Request("GET", "https://example.com"))


def test_http_assertion_matrix() -> None:
    assertions = HttpAssertions.model_validate(
        {
            "status": [200, 201],
            "header_equals": {"x-mode": "real"},
            "header_contains": {"x-mode": "ea"},
            "body_contains": "alpha",
            "body_not_contains": "fallback",
            "body_matches": "items",
            "json": [
                {"path": "$.name", "equals": "alpha"},
                {"path": "$.name", "not_equals": "beta"},
                {"path": "$.name", "contains": "alp"},
                {"path": "$.items", "contains": 2},
                {"path": "$.missing", "exists": False},
                {"path": "$.name", "matches": "^a"},
            ],
            "max_duration_ms": 100,
        }
    )
    _assert_http(response(), assertions, 10)
    failures = [
        ({"status": 201}, "status"),
        ({"header_equals": {"x-mode": "wrong"}}, "Header"),
        ({"header_contains": {"x-mode": "zzz"}}, "does not contain"),
        ({"body_contains": "zzz"}, "does not contain"),
        ({"body_not_contains": "alpha"}, "forbidden"),
        ({"body_matches": "zzz"}, "does not match"),
        ({"max_duration_ms": 1}, "limit"),
    ]
    for raw, message in failures:
        with pytest.raises(StepExecutionError, match=message):
            _assert_http(response(), HttpAssertions.model_validate(raw), 10)
    with pytest.raises(StepExecutionError, match="not valid JSON"):
        _assert_http(response(body="not-json"), HttpAssertions.model_validate({"json": [{"path": "$.x", "exists": True}]}), 1)


def test_json_and_network_negative_branches() -> None:
    with pytest.raises(StepExecutionError, match="does not exist"):
        _assert_json(JsonAssertion(path="$.x", equals=1), {})
    with pytest.raises(StepExecutionError, match="unexpectedly equals"):
        _assert_json(JsonAssertion(path="$.x", not_equals=1), {"x": 1})
    with pytest.raises(StepExecutionError, match="does not contain"):
        _assert_json(JsonAssertion(path="$.x", contains={"a": 2}), {"x": {"a": 1}})
    with pytest.raises(StepExecutionError, match="does not match"):
        _assert_json(JsonAssertion(path="$.x", matches="z"), {"x": "a"})

    state = RuntimeState(
        context_values={},
        network=[
            NetworkRecord(kind="request", url="https://x/api", method="POST", request_body="hello"),
            NetworkRecord(kind="response", url="https://x/api", method="POST", status=201, response_body="world"),
            NetworkRecord(kind="response", url="https://x/api", method="POST", status=500, response_body="bad"),
        ],
    )
    result = _network_assert(NetworkAssertStep(type="network.assert", kind="response", url_matches=r"/api$", method="POST", status=201, body_contains="world", minimum=1, maximum=1), state, {})
    assert result["matched"] == 1
    with pytest.raises(StepExecutionError, match="maximum"):
        _network_assert(NetworkAssertStep(type="network.assert", url_contains="/api", minimum=0, maximum=1), state, {})
