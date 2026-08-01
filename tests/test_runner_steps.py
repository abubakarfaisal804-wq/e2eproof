from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from playwright.sync_api import sync_playwright
from pydantic import TypeAdapter

from e2eproof.errors import StepExecutionError
from e2eproof.models import Contract, Step
from e2eproof.runner import (
    AttemptRuntime,
    NetworkRecord,
    RuntimeState,
    _attach_observers,
    _check_policy,
    _execute_step,
    _step_screenshot_mode,
)
from e2eproof.utils import Redactor

STEP = TypeAdapter(Step)


def contract(base_url: str = "https://example.com", **policy: Any) -> Contract:
    return Contract.model_validate(
        {
            "version": 1,
            "name": "Step execution contract",
            "base_url": base_url,
            "policy": {"allowed_hosts": ["example.com", "127.0.0.1", "localhost"], **policy},
            "flows": [
                {
                    "id": "steps",
                    "claim": "Individual verification steps behave correctly.",
                    "steps": [{"type": "browser.goto", "url": "/"}],
                }
            ],
        }
    )


def run_step(raw: dict[str, Any], runtime: AttemptRuntime, c: Contract, client: httpx.Client):
    return _execute_step(STEP.validate_python(raw), runtime=runtime, contract=c, http_client=client)


@pytest.mark.browser
def test_browser_step_matrix(tmp_path: Path) -> None:
    with sync_playwright() as playwright, httpx.Client() as client:
        browser = playwright.chromium.launch(
            headless=True, executable_path="/usr/bin/chromium", args=["--no-sandbox"]
        )
        context = browser.new_context()
        page = context.new_page()
        page.set_content(
            """<html lang='en'><head><title>Matrix</title></head><body>
            <label>Email<input id='email' value='old'></label>
            <label>Choice<select id='choice'><option value='a'>A</option><option value='b'>B</option></select></label>
            <label><input id='check' type='checkbox'> Agree</label>
            <button id='button'>Save</button><p id='status'>Ready now</p>
            <div class='item'>one</div><div class='item'>two</div><div id='hidden' hidden>hidden</div>
            </body></html>"""
        )
        flow_dir = tmp_path / "flow"
        flow_dir.mkdir()
        state = RuntimeState(context_values={"email": "new@example.com", "key": "End"})
        runtime = AttemptRuntime(context, page, state, flow_dir, None)
        c = contract()

        run_step(
            {"type": "browser.fill", "target": {"label": "Email"}, "value": "{{email}}"},
            runtime,
            c,
            client,
        )
        assert page.locator("#email").input_value() == "new@example.com"
        run_step(
            {"type": "browser.assert_value", "target": "#email", "equals": "new@example.com"},
            runtime,
            c,
            client,
        )
        run_step(
            {"type": "browser.assert_value", "target": "#email", "contains": "@example"},
            runtime,
            c,
            client,
        )
        run_step(
            {"type": "browser.assert_value", "target": "#email", "matches": r"^new@"},
            runtime,
            c,
            client,
        )
        with pytest.raises(StepExecutionError, match="expected"):
            run_step(
                {"type": "browser.assert_value", "target": "#email", "equals": "bad"},
                runtime,
                c,
                client,
            )

        run_step({"type": "browser.select", "target": "#choice", "value": "b"}, runtime, c, client)
        assert page.locator("#choice").input_value() == "b"
        run_step({"type": "browser.check", "target": "#check", "checked": True}, runtime, c, client)
        assert page.locator("#check").is_checked()
        run_step(
            {"type": "browser.check", "target": "#check", "checked": False}, runtime, c, client
        )
        assert not page.locator("#check").is_checked()

        run_step(
            {"type": "browser.press", "target": "#email", "key": "{{key}}"}, runtime, c, client
        )
        run_step({"type": "browser.press", "key": "Escape"}, runtime, c, client)
        run_step({"type": "browser.wait", "milliseconds": 1}, runtime, c, client)
        run_step(
            {"type": "browser.wait", "target": "#status", "state": "visible"}, runtime, c, client
        )

        run_step(
            {"type": "browser.assert_text", "target": "#status", "equals": "Ready now"},
            runtime,
            c,
            client,
        )
        run_step(
            {"type": "browser.assert_text", "target": "#status", "contains": "Ready"},
            runtime,
            c,
            client,
        )
        run_step(
            {"type": "browser.assert_text", "target": "#status", "not_contains": "Failed"},
            runtime,
            c,
            client,
        )
        run_step(
            {"type": "browser.assert_text", "target": "#status", "matches": "Ready\\s+now"},
            runtime,
            c,
            client,
        )
        with pytest.raises(StepExecutionError, match="unexpectedly"):
            run_step(
                {"type": "browser.assert_text", "target": "#status", "not_contains": "Ready"},
                runtime,
                c,
                client,
            )
        with pytest.raises(StepExecutionError, match="does not match"):
            run_step(
                {"type": "browser.assert_text", "target": "#status", "matches": "Never"},
                runtime,
                c,
                client,
            )

        run_step(
            {"type": "browser.assert_visible", "target": "#status", "visible": True},
            runtime,
            c,
            client,
        )
        run_step(
            {"type": "browser.assert_visible", "target": "#hidden", "visible": False},
            runtime,
            c,
            client,
        )
        run_step(
            {"type": "browser.assert_count", "target": ".item", "equals": 2}, runtime, c, client
        )
        run_step(
            {"type": "browser.assert_count", "target": ".item", "minimum": 1, "maximum": 3},
            runtime,
            c,
            client,
        )
        with pytest.raises(StepExecutionError, match="expected 1"):
            run_step(
                {"type": "browser.assert_count", "target": ".item", "equals": 1}, runtime, c, client
            )

        page.locator("#button").evaluate(
            "el => el.addEventListener('click', () => document.querySelector('#status').textContent='Saved')"
        )
        run_step(
            {"type": "browser.click", "target": {"role": "button", "name": "Save"}},
            runtime,
            c,
            client,
        )
        assert page.locator("#status").inner_text() == "Saved"

        _, _extract = run_step(
            {"type": "browser.extract", "target": "#status", "variable": "saved_text"},
            runtime,
            c,
            client,
        )
        assert state.context_values["saved_text"] == "Saved"
        page.locator("#status").evaluate('el => el.setAttribute("data-x", "42")')
        run_step(
            {
                "type": "browser.extract",
                "target": "#status",
                "variable": "attr",
                "attribute": "data-x",
            },
            runtime,
            c,
            client,
        )
        assert state.context_values["attr"] == "42"

        _, shot = run_step(
            {"type": "browser.screenshot", "name": "matrix", "full_page": False}, runtime, c, client
        )
        assert Path(shot["artifact_path"]).exists()
        _, accessibility = run_step(
            {"type": "browser.audit_accessibility", "maximum_violations": 0}, runtime, c, client
        )
        assert accessibility["count"] == 0
        _, performance = run_step(
            {"type": "browser.assert_performance", "max_load_ms": 999999}, runtime, c, client
        )
        assert "resource_count" in performance

        run_step({"type": "browser.assert_url", "contains": "about:blank"}, runtime, c, client)
        run_step({"type": "browser.assert_url", "matches": "about:blank"}, runtime, c, client)
        with pytest.raises(StepExecutionError, match="does not contain"):
            run_step({"type": "browser.assert_url", "contains": "missing"}, runtime, c, client)

        _, set_details = run_step(
            {"type": "set.variable", "variable": "nested", "value": "{{email}}"}, runtime, c, client
        )
        assert set_details["value"] == "new@example.com"

        state.network.extend(
            [
                NetworkRecord(
                    kind="request",
                    url="https://example.com/api",
                    method="POST",
                    request_body="hello",
                ),
                NetworkRecord(
                    kind="response",
                    url="https://example.com/api",
                    method="POST",
                    status=201,
                    response_body='{"ok":true}',
                ),
            ]
        )
        _, net = run_step(
            {
                "type": "network.assert",
                "kind": "response",
                "url_contains": "/api",
                "method": "POST",
                "status": 201,
                "minimum": 1,
                "maximum": 1,
            },
            runtime,
            c,
            client,
        )
        assert net["matched"] == 1
        with pytest.raises(StepExecutionError, match="minimum"):
            run_step(
                {"type": "network.assert", "url_contains": "/nope", "minimum": 1},
                runtime,
                c,
                client,
            )

        assert (
            _step_screenshot_mode(
                STEP.validate_python(
                    {"type": "browser.wait", "milliseconds": 1, "evidence": "always"}
                ),
                c,
            )
            == "always"
        )
        context.close()
        browser.close()


@pytest.mark.browser
def test_observers_and_policy_gates() -> None:
    c = contract(
        fail_on_console_error=True,
        fail_on_page_error=True,
        fail_on_request_failure=True,
        forbidden_network_markers=["mock response"],
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path="/usr/bin/chromium", args=["--no-sandbox"]
        )
        page = browser.new_page()
        state = RuntimeState(context_values={})
        _attach_observers(page, state, c, Redactor([]))
        page.set_content("<html lang='en'><title>x</title><body>ok</body></html>")
        page.evaluate("console.error('boom')")
        assert any(item["type"] == "error" for item in state.console)
        with pytest.raises(StepExecutionError, match="console error"):
            _check_policy(page, state, c, (0, 0, 0, 0))

        state2 = RuntimeState(context_values={}, page_errors=["uncaught"])
        with pytest.raises(StepExecutionError, match="Uncaught"):
            _check_policy(page, state2, c, (0, 0, 0, 0))
        state3 = RuntimeState(context_values={}, request_failures=["GET x failed"])
        with pytest.raises(StepExecutionError, match="Network request failure"):
            _check_policy(page, state3, c, (0, 0, 0, 0))
        state4 = RuntimeState(
            context_values={},
            network=[
                NetworkRecord(
                    kind="response",
                    url="https://example.com",
                    method="GET",
                    response_body="mock response",
                )
            ],
        )
        with pytest.raises(StepExecutionError, match="Forbidden network marker"):
            _check_policy(page, state4, c, (0, 0, 0, 0))
        browser.close()
