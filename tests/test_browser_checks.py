from __future__ import annotations

import pytest
from playwright.sync_api import sync_playwright

from e2eproof.errors import StepExecutionError
from e2eproof.models import BrowserAccessibilityStep, Contract
from e2eproof.runner import RuntimeState, _audit_accessibility, _check_policy


def _contract(**policy: object) -> Contract:
    return Contract.model_validate(
        {
            "version": 1,
            "name": "Browser policy test",
            "base_url": "https://example.com",
            "policy": policy,
            "flows": [
                {
                    "id": "x",
                    "claim": "Browser policy behaves deterministically.",
                    "steps": [{"type": "browser.goto", "url": "/"}],
                }
            ],
        }
    )


@pytest.mark.browser
def test_accessibility_baseline_and_visible_marker(
    chromium_launch_options: dict[str, object],
) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**chromium_launch_options)
        page = browser.new_page()
        page.set_content(
            '<html lang="en"><head><title>x</title></head><body><label>Email<input></label><button>Save</button></body></html>'
        )
        details = _audit_accessibility(
            page, BrowserAccessibilityStep(type="browser.audit_accessibility")
        )
        assert details["count"] == 0
        page.set_content(
            "<html><head></head><body><input><button></button><p>fallback active</p></body></html>"
        )
        with pytest.raises(StepExecutionError, match="Accessibility"):
            _audit_accessibility(page, BrowserAccessibilityStep(type="browser.audit_accessibility"))
        state = RuntimeState(context_values={})
        with pytest.raises(StepExecutionError, match="Forbidden visible marker"):
            _check_policy(
                page,
                state,
                _contract(forbidden_visible_markers=["fallback active"]),
                (0, 0, 0, 0),
            )
        browser.close()
