from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Locator,
    Page,
    Playwright,
    expect,
    sync_playwright,
)
from playwright.sync_api import (
    Error as PlaywrightError,
)
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from . import __version__
from .errors import ContractError, E2EProofError, StepExecutionError
from .evidence import EvidenceBundle
from .models import (
    BrowserAccessibilityStep,
    BrowserAssertCountStep,
    BrowserAssertTextStep,
    BrowserAssertUrlStep,
    BrowserAssertValueStep,
    BrowserAssertVisibleStep,
    BrowserCheckStep,
    BrowserClickStep,
    BrowserExtractStep,
    BrowserFillStep,
    BrowserGotoStep,
    BrowserPerformanceStep,
    BrowserPressStep,
    BrowserScreenshotStep,
    BrowserSelectStep,
    BrowserWaitStep,
    Contract,
    HttpAssertions,
    HttpPollStep,
    HttpRequestStep,
    JsonAssertion,
    LocatorSpec,
    NetworkAssertStep,
    SetVariableStep,
    Step,
)
from .report import generate_html_report, write_junit
from .results import FlowAttempt, FlowResult, RunResult, StepResult
from .utils import (
    Redactor,
    compile_patterns,
    json_path_get,
    load_secret_environment,
    make_run_id,
    normalize_text,
    resolve_template_string,
    resolve_templates,
    resolve_url,
    safe_slug,
    sha256_file,
    utc_iso,
    validate_url_allowed,
)

# The odd alias above is intentionally avoided at runtime; it makes accidental model renames fail typecheck.


@dataclass
class NetworkRecord:
    kind: str
    url: str
    method: str
    status: int | None = None
    resource_type: str | None = None
    request_body: str | None = None
    response_body: str | None = None
    content_type: str | None = None
    failure: str | None = None
    timestamp: str = field(default_factory=utc_iso)


@dataclass
class RuntimeState:
    context_values: dict[str, Any]
    network: list[NetworkRecord] = field(default_factory=list)
    console: list[dict[str, Any]] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)
    request_failures: list[str] = field(default_factory=list)
    browser_version: str | None = None


@dataclass
class AttemptRuntime:
    browser_context: BrowserContext
    page: Page
    state: RuntimeState
    flow_dir: Path
    trace_temp_path: Path | None


def _elapsed_ms(start: float) -> int:
    return max(0, round((time.perf_counter() - start) * 1000))


def _resolve_variables(
    raw: dict[str, Any], builtins: dict[str, Any], secrets: dict[str, str]
) -> dict[str, Any]:
    resolved = dict(raw)
    context: dict[str, Any] = {**builtins, **resolved, "secret": secrets}
    # Resolve references in a bounded loop so cycles fail clearly.
    for _ in range(len(raw) + 2):
        changed = False
        for key, value in list(resolved.items()):
            new_value = resolve_templates(value, {**context, **resolved})
            if new_value != value:
                resolved[key] = new_value
                changed = True
        context.update(resolved)
        if not changed:
            break
    # One final resolution catches unresolved/unknown references.
    return resolve_templates(resolved, {**builtins, **resolved, "secret": secrets})


def _git_commit(cwd: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", value) else None


def find_browser_executable(engine: str) -> str | None:
    override = os.getenv("E2EPROOF_BROWSER_PATH")
    if override and Path(override).is_file():
        return override
    if engine != "chromium":
        return None

    candidates = [
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("msedge"),
    ]
    if sys.platform == "win32":
        roots = [
            os.getenv("PROGRAMFILES"),
            os.getenv("PROGRAMFILES(X86)"),
            os.getenv("LOCALAPPDATA"),
        ]
        relative_paths = [
            Path("Google/Chrome/Application/chrome.exe"),
            Path("Microsoft/Edge/Application/msedge.exe"),
            Path("Chromium/Application/chrome.exe"),
        ]
        for root in roots:
            if root:
                candidates.extend(str(Path(root) / rel) for rel in relative_paths)
    elif sys.platform == "darwin":
        candidates.extend(
            [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
            ]
        )

    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return None


def _launch_browser(playwright: Playwright, contract: Contract) -> Browser:
    browser_type = getattr(playwright, contract.browser.engine)
    kwargs: dict[str, Any] = {"headless": contract.browser.headless}
    executable = contract.browser.executable_path or find_browser_executable(
        contract.browser.engine
    )
    if contract.browser.executable_path and not Path(contract.browser.executable_path).is_file():
        raise ContractError(
            f"Configured browser executable does not exist: {contract.browser.executable_path}"
        )
    if executable:
        kwargs["executable_path"] = executable
    if contract.browser.channel:
        kwargs["channel"] = contract.browser.channel
    if (
        contract.browser.engine == "chromium"
        and sys.platform.startswith("linux")
        and os.geteuid() == 0
    ):
        kwargs["args"] = ["--no-sandbox"]
    try:
        return browser_type.launch(**kwargs)
    except PlaywrightError as error:
        hint = (
            f"Run 'e2eproof install-browser {contract.browser.engine}', configure "
            "browser.executable_path, or set E2EPROOF_BROWSER_PATH."
        )
        raise ContractError(
            f"Could not launch {contract.browser.engine}: {error}\n{hint}"
        ) from error


def _create_context(browser: Browser, contract: Contract) -> BrowserContext:
    kwargs: dict[str, Any] = {
        "viewport": {
            "width": contract.browser.viewport_width,
            "height": contract.browser.viewport_height,
        },
        "locale": contract.browser.locale,
        "color_scheme": contract.browser.color_scheme,
        "ignore_https_errors": contract.browser.ignore_https_errors,
    }
    if contract.browser.timezone_id:
        kwargs["timezone_id"] = contract.browser.timezone_id
    if contract.browser.user_agent:
        kwargs["user_agent"] = contract.browser.user_agent
    context = browser.new_context(**kwargs)
    context.set_default_timeout(contract.policy.timeout_ms)
    context.set_default_navigation_timeout(contract.policy.navigation_timeout_ms)
    if contract.policy.enforce_browser_host_allowlist:

        def enforce_allowlist(route: Any, request: Any) -> None:
            parsed = urlparse(request.url)
            if parsed.scheme in {"http", "https"}:
                try:
                    validate_url_allowed(
                        request.url,
                        base_url=contract.base_url,
                        allowed_hosts=contract.policy.allowed_hosts,
                        allowed_schemes=contract.policy.allowed_schemes,
                    )
                except ContractError:
                    route.abort("blockedbyclient")
                    return
            route.continue_()

        context.route("**/*", enforce_allowlist)
    return context


def _locator(page: Page, target: str | LocatorSpec) -> Locator:
    if isinstance(target, str):
        return page.locator(target)
    if target.css is not None:
        locator = page.locator(target.css)
    elif target.role is not None:
        locator = page.get_by_role(target.role, name=target.name, exact=target.exact)
    elif target.text is not None:
        locator = page.get_by_text(target.text, exact=target.exact)
    elif target.label is not None:
        locator = page.get_by_label(target.label, exact=target.exact)
    elif target.placeholder is not None:
        locator = page.get_by_placeholder(target.placeholder, exact=target.exact)
    elif target.test_id is not None:
        locator = page.get_by_test_id(target.test_id)
    else:  # Pydantic validation makes this unreachable.
        raise StepExecutionError("Invalid locator")
    if target.nth is not None:
        locator = locator.nth(target.nth)
    return locator


def _matches_ignore(value: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(pattern.search(value) for pattern in patterns)


def _attach_observers(
    page: Page,
    state: RuntimeState,
    contract: Contract,
    redactor: Redactor,
) -> None:
    console_ignore = compile_patterns(contract.policy.console_error_ignore)
    request_ignore = compile_patterns(contract.policy.request_failure_ignore)

    def on_console(message: Any) -> None:
        record = {
            "timestamp": utc_iso(),
            "type": message.type,
            "text": redactor.text(message.text),
            "location": redactor.value(message.location),
        }
        state.console.append(record)
        if message.type == "error" and not _matches_ignore(message.text, console_ignore):
            # Stored in console; policy gate will decide whether it fails.
            pass

    def on_page_error(error: Any) -> None:
        state.page_errors.append(redactor.text(str(error)))

    def on_request(request: Any) -> None:
        state.network.append(
            NetworkRecord(
                kind="request",
                url=redactor.text(request.url),
                method=request.method,
                resource_type=request.resource_type,
                request_body=redactor.text(request.post_data or "") or None,
            )
        )

    def on_request_failed(request: Any) -> None:
        failure = request.failure or "unknown request failure"
        text = f"{request.method} {request.url}: {failure}"
        if not _matches_ignore(text, request_ignore):
            state.request_failures.append(redactor.text(text))
        state.network.append(
            NetworkRecord(
                kind="failure",
                url=redactor.text(request.url),
                method=request.method,
                resource_type=request.resource_type,
                failure=redactor.text(failure),
            )
        )

    def on_response(response: Any) -> None:
        content_type = response.headers.get("content-type", "")
        body: str | None = None
        should_read = (
            "json" in content_type
            or content_type.startswith("text/")
            or "javascript" in content_type
            or "xml" in content_type
        )
        if should_read and contract.evidence.max_response_body_bytes > 0:
            try:
                raw = response.body()
                raw = raw[: contract.evidence.max_response_body_bytes]
                body = redactor.text(raw.decode("utf-8", errors="replace"))
            except PlaywrightError:
                body = None
        state.network.append(
            NetworkRecord(
                kind="response",
                url=redactor.text(response.url),
                method=response.request.method,
                status=response.status,
                resource_type=response.request.resource_type,
                response_body=body,
                content_type=content_type,
            )
        )

    page.on("console", on_console)
    page.on("pageerror", on_page_error)
    page.on("request", on_request)
    page.on("requestfailed", on_request_failed)
    page.on("response", on_response)


def _check_policy(
    page: Page,
    state: RuntimeState,
    contract: Contract,
    baseline: tuple[int, int, int, int],
) -> None:
    console_start, page_error_start, request_failure_start, network_start = baseline
    if contract.policy.fail_on_console_error:
        console_ignore = compile_patterns(contract.policy.console_error_ignore)
        errors = [
            item["text"]
            for item in state.console[console_start:]
            if item["type"] == "error" and not _matches_ignore(item["text"], console_ignore)
        ]
        if errors:
            raise StepExecutionError("Browser console error: " + " | ".join(errors[:3]))
    if contract.policy.fail_on_page_error and len(state.page_errors) > page_error_start:
        raise StepExecutionError(
            "Uncaught page error: " + " | ".join(state.page_errors[page_error_start:][:3])
        )
    if (
        contract.policy.fail_on_request_failure
        and len(state.request_failures) > request_failure_start
    ):
        raise StepExecutionError(
            "Network request failure: "
            + " | ".join(state.request_failures[request_failure_start:][:3])
        )

    if contract.policy.forbidden_visible_markers:
        try:
            visible_text = page.locator("body").inner_text(timeout=1000)
        except PlaywrightError:
            visible_text = ""
        for marker in contract.policy.forbidden_visible_markers:
            if marker.casefold() in visible_text.casefold():
                raise StepExecutionError(f"Forbidden visible marker detected: {marker!r}")

    if contract.policy.forbidden_network_markers:
        recent_network = state.network[network_start:]
        for record in recent_network:
            body = record.response_body or ""
            for marker in contract.policy.forbidden_network_markers:
                if marker.casefold() in body.casefold():
                    raise StepExecutionError(
                        f"Forbidden network marker detected in {record.url}: {marker!r}"
                    )


def _assert_json(assertion: JsonAssertion, payload: Any) -> None:
    exists, actual = json_path_get(payload, assertion.path)
    if assertion.exists is not None:
        if exists != assertion.exists:
            raise StepExecutionError(
                f"JSON path {assertion.path} existence was {exists}, expected {assertion.exists}"
            )
        return
    if not exists:
        raise StepExecutionError(f"JSON path does not exist: {assertion.path}")
    if assertion.equals is not None and actual != assertion.equals:
        raise StepExecutionError(
            f"JSON {assertion.path} was {actual!r}, expected {assertion.equals!r}"
        )
    if assertion.not_equals is not None and actual == assertion.not_equals:
        raise StepExecutionError(
            f"JSON {assertion.path} unexpectedly equals {assertion.not_equals!r}"
        )
    if assertion.contains is not None:
        expected = assertion.contains
        if isinstance(actual, str):
            matched = str(expected) in actual
        elif isinstance(actual, list):
            matched = expected in actual
        elif isinstance(actual, dict) and isinstance(expected, dict):
            matched = all(actual.get(key) == value for key, value in expected.items())
        else:
            matched = False
        if not matched:
            raise StepExecutionError(f"JSON {assertion.path} does not contain {expected!r}")
    if assertion.matches is not None and re.search(assertion.matches, str(actual)) is None:
        raise StepExecutionError(
            f"JSON {assertion.path} value {actual!r} does not match {assertion.matches!r}"
        )


def _assert_http(response: httpx.Response, assertions: HttpAssertions, duration_ms: int) -> None:
    if assertions.status is not None:
        expected_statuses = (
            [assertions.status] if isinstance(assertions.status, int) else assertions.status
        )
        if response.status_code not in expected_statuses:
            raise StepExecutionError(
                f"HTTP status {response.status_code}, expected {expected_statuses}"
            )
    for name, expected in assertions.header_equals.items():
        actual = response.headers.get(name)
        if actual != expected:
            raise StepExecutionError(f"Header {name!r} was {actual!r}, expected {expected!r}")
    for name, expected in assertions.header_contains.items():
        actual = response.headers.get(name, "")
        if expected not in actual:
            raise StepExecutionError(f"Header {name!r} does not contain {expected!r}")
    text = response.text
    if assertions.body_contains is not None and assertions.body_contains not in text:
        raise StepExecutionError(f"Response body does not contain {assertions.body_contains!r}")
    if assertions.body_not_contains is not None and assertions.body_not_contains in text:
        raise StepExecutionError(
            f"Response body contains forbidden value {assertions.body_not_contains!r}"
        )
    if assertions.body_matches is not None and re.search(assertions.body_matches, text) is None:
        raise StepExecutionError(f"Response body does not match {assertions.body_matches!r}")
    if assertions.json_assertions:
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as error:
            raise StepExecutionError(f"Response is not valid JSON: {error}") from error
        for assertion in assertions.json_assertions:
            _assert_json(assertion, payload)
    if assertions.max_duration_ms is not None and duration_ms > assertions.max_duration_ms:
        raise StepExecutionError(
            f"HTTP request took {duration_ms} ms, limit is {assertions.max_duration_ms} ms"
        )


def _http_request(
    step: HttpRequestStep,
    contract: Contract,
    values: dict[str, Any],
    client: httpx.Client,
) -> tuple[httpx.Response, int, dict[str, Any]]:
    data = step.model_dump(exclude={"type", "id", "continue_on_failure", "evidence", "timeout_ms"})
    resolved = resolve_templates(data, values)
    url = resolve_url(contract.base_url, resolved["url"])
    validate_url_allowed(
        url,
        base_url=contract.base_url,
        allowed_hosts=contract.policy.allowed_hosts,
        allowed_schemes=contract.policy.allowed_schemes,
    )
    kwargs: dict[str, Any] = {
        "headers": resolved["headers"],
        "params": resolved["params"],
        "timeout": (step.timeout_ms or contract.policy.timeout_ms) / 1000,
    }
    if resolved.get("json_body") is not None:
        kwargs["json"] = resolved["json_body"]
    elif resolved.get("body") is not None:
        kwargs["content"] = resolved["body"]
    started = time.perf_counter()
    try:
        response = client.request(resolved["method"], url, **kwargs)
    except httpx.HTTPError as error:
        raise StepExecutionError(f"HTTP request failed: {error}") from error
    duration_ms = _elapsed_ms(started)
    return response, duration_ms, resolved


def _network_assert(
    step: NetworkAssertStep, state: RuntimeState, values: dict[str, Any]
) -> dict[str, Any]:
    resolved = resolve_templates(step.model_dump(), values)
    matches: list[NetworkRecord] = []
    regex = re.compile(resolved["url_matches"]) if resolved.get("url_matches") else None
    for record in state.network:
        if resolved["kind"] != "either" and record.kind != resolved["kind"]:
            continue
        if resolved.get("url_contains") and resolved["url_contains"] not in record.url:
            continue
        if regex and regex.search(record.url) is None:
            continue
        if resolved.get("method") and record.method.upper() != resolved["method"].upper():
            continue
        if resolved.get("status") is not None and record.status != resolved["status"]:
            continue
        body = record.response_body or record.request_body or ""
        if resolved.get("body_contains") and resolved["body_contains"] not in body:
            continue
        if resolved.get("body_not_contains") and resolved["body_not_contains"] in body:
            continue
        matches.append(record)
    count = len(matches)
    if count < resolved["minimum"]:
        raise StepExecutionError(
            f"Network assertion matched {count} records; minimum is {resolved['minimum']}"
        )
    if resolved.get("maximum") is not None and count > resolved["maximum"]:
        raise StepExecutionError(
            f"Network assertion matched {count} records; maximum is {resolved['maximum']}"
        )
    return {
        "matched": count,
        "records": [
            {"kind": item.kind, "method": item.method, "url": item.url, "status": item.status}
            for item in matches[:20]
        ],
    }


def _audit_accessibility(page: Page, step: BrowserAccessibilityStep) -> dict[str, Any]:
    options = step.model_dump()
    result = page.evaluate(
        r"""
        (options) => {
          const violations = [];
          const visible = (el) => {
            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
          };
          const accessibleName = (el) => {
            const aria = (el.getAttribute('aria-label') || '').trim();
            if (aria) return aria;
            const labelledBy = (el.getAttribute('aria-labelledby') || '').trim();
            if (labelledBy) {
              const text = labelledBy.split(/\s+/).map(id => document.getElementById(id)?.textContent || '').join(' ').trim();
              if (text) return text;
            }
            if (el.labels && el.labels.length) {
              const text = Array.from(el.labels).map(label => label.textContent || '').join(' ').trim();
              if (text) return text;
            }
            const text = (el.textContent || '').trim();
            if (text) return text;
            return (el.getAttribute('title') || '').trim();
          };
          if (options.require_title && !document.title.trim()) violations.push({rule:'document-title', target:'html', message:'Document has no title'});
          if (options.require_html_lang && !(document.documentElement.getAttribute('lang') || '').trim()) violations.push({rule:'html-lang', target:'html', message:'html element has no lang attribute'});
          if (options.require_image_alt) {
            document.querySelectorAll('img').forEach((img, index) => {
              if (!visible(img)) return;
              const role = img.getAttribute('role');
              if (role === 'presentation' || role === 'none') return;
              if (!img.hasAttribute('alt')) violations.push({rule:'image-alt', target:`img:nth-of-type(${index+1})`, message:'Visible image has no alt attribute'});
            });
          }
          if (options.require_control_names) {
            document.querySelectorAll('input:not([type=hidden]), select, textarea').forEach((el, index) => {
              if (visible(el) && !accessibleName(el)) violations.push({rule:'control-name', target:`control-${index+1}`, message:'Visible form control has no accessible name'});
            });
          }
          if (options.require_button_names) {
            document.querySelectorAll('button, a[href], [role=button]').forEach((el, index) => {
              if (visible(el) && !accessibleName(el)) violations.push({rule:'interactive-name', target:`interactive-${index+1}`, message:'Visible interactive element has no accessible name'});
            });
          }
          return {violations};
        }
        """,
        options,
    )
    violations = result["violations"]
    if len(violations) > step.maximum_violations:
        messages = "; ".join(item["message"] for item in violations[:5])
        raise StepExecutionError(
            f"Accessibility baseline found {len(violations)} violations "
            f"(allowed {step.maximum_violations}): {messages}"
        )
    return {"violations": violations, "count": len(violations), "scope": "baseline-not-full-wcag"}


def _assert_performance(page: Page, step: BrowserPerformanceStep) -> dict[str, Any]:
    metrics = page.evaluate(
        """
        () => {
          const nav = performance.getEntriesByType('navigation')[0];
          const resources = performance.getEntriesByType('resource');
          return {
            dom_content_loaded_ms: nav ? Math.round(nav.domContentLoadedEventEnd) : null,
            load_ms: nav ? Math.round(nav.loadEventEnd) : null,
            transfer_bytes: Math.round((nav?.transferSize || 0) + resources.reduce((sum, r) => sum + (r.transferSize || 0), 0)),
            resource_count: resources.length
          };
        }
        """
    )
    checks = [
        (step.max_dom_content_loaded_ms, metrics["dom_content_loaded_ms"], "DOM content loaded"),
        (step.max_load_ms, metrics["load_ms"], "Page load"),
        (step.max_transfer_bytes, metrics["transfer_bytes"], "Transfer size"),
    ]
    for maximum, actual, label in checks:
        if maximum is not None and actual is not None and actual > maximum:
            raise StepExecutionError(f"{label} was {actual}, limit is {maximum}")
    return metrics


def _execute_step(
    step: Step,
    *,
    runtime: AttemptRuntime,
    contract: Contract,
    http_client: httpx.Client,
) -> tuple[str, dict[str, Any]]:
    page = runtime.page
    values = runtime.state.context_values
    timeout = step.timeout_ms or contract.policy.timeout_ms

    if isinstance(step, BrowserGotoStep):
        url = resolve_url(contract.base_url, resolve_template_string(step.url, values))
        validate_url_allowed(
            url,
            base_url=contract.base_url,
            allowed_hosts=contract.policy.allowed_hosts,
            allowed_schemes=contract.policy.allowed_schemes,
        )
        response = page.goto(url, wait_until=step.wait_until, timeout=timeout)
        validate_url_allowed(
            page.url,
            base_url=contract.base_url,
            allowed_hosts=contract.policy.allowed_hosts,
            allowed_schemes=contract.policy.allowed_schemes,
        )
        if response is not None and response.status >= 400:
            raise StepExecutionError(f"Navigation returned HTTP {response.status}: {url}")
        return f"Navigated to {url}", {
            "url": page.url,
            "status": response.status if response else None,
        }

    if isinstance(step, BrowserFillStep):
        locator = _locator(page, step.target)
        value = resolve_template_string(step.value, values)
        locator.fill(value, timeout=timeout)
        return "Filled field", {
            "target": step.target.model_dump()
            if isinstance(step.target, LocatorSpec)
            else step.target
        }

    if isinstance(step, BrowserClickStep):
        locator = _locator(page, step.target)
        locator.click(button=step.button, click_count=step.click_count, timeout=timeout)
        return "Clicked element", {
            "target": step.target.model_dump()
            if isinstance(step.target, LocatorSpec)
            else step.target
        }

    if isinstance(step, BrowserPressStep):
        key = resolve_template_string(step.key, values)
        if step.target is None:
            page.keyboard.press(key)
        else:
            _locator(page, step.target).press(key, timeout=timeout)
        return f"Pressed {key}", {}

    if isinstance(step, BrowserSelectStep):
        value = resolve_templates(step.value, values)
        _locator(page, step.target).select_option(value=value, timeout=timeout)
        return "Selected option", {"value": value}

    if isinstance(step, BrowserCheckStep):
        locator = _locator(page, step.target)
        if step.checked:
            locator.check(timeout=timeout)
        else:
            locator.uncheck(timeout=timeout)
        return "Updated checkbox", {"checked": step.checked}

    if isinstance(step, BrowserWaitStep):
        if step.milliseconds is not None:
            page.wait_for_timeout(step.milliseconds)
            return f"Waited {step.milliseconds} ms", {}
        assert step.target is not None
        _locator(page, step.target).wait_for(state=step.state, timeout=timeout)
        return f"Element reached state {step.state}", {}

    if isinstance(step, BrowserAssertTextStep):
        locator = page.locator("body") if step.target is None else _locator(page, step.target)
        if step.equals is not None:
            expected = resolve_template_string(step.equals, values)
            expect(locator).to_have_text(expected, timeout=timeout)
            message = f"Text equals {expected!r}"
        elif step.contains is not None:
            expected = resolve_template_string(step.contains, values)
            expect(locator).to_contain_text(expected, timeout=timeout)
            message = f"Text contains {expected!r}"
        elif step.not_contains is not None:
            forbidden = resolve_template_string(step.not_contains, values)
            actual = locator.inner_text(timeout=timeout)
            if forbidden in actual:
                raise StepExecutionError(f"Text unexpectedly contains {forbidden!r}")
            message = f"Text does not contain {forbidden!r}"
        else:
            assert step.matches is not None
            pattern = resolve_template_string(step.matches, values)
            actual = locator.inner_text(timeout=timeout)
            tested = normalize_text(actual) if step.normalize_whitespace else actual
            if re.search(pattern, tested) is None:
                raise StepExecutionError(f"Text does not match {pattern!r}")
            message = f"Text matches {pattern!r}"
        return message, {}

    if isinstance(step, BrowserAssertVisibleStep):
        locator = _locator(page, step.target)
        if step.visible:
            expect(locator).to_be_visible(timeout=timeout)
        else:
            expect(locator).to_be_hidden(timeout=timeout)
        return f"Element visibility is {step.visible}", {}

    if isinstance(step, BrowserAssertUrlStep):
        actual = page.url
        if step.equals is not None:
            expected = resolve_template_string(step.equals, values)
            expected = resolve_url(contract.base_url, expected)
            if actual != expected:
                raise StepExecutionError(f"URL was {actual!r}, expected {expected!r}")
        elif step.contains is not None:
            expected = resolve_template_string(step.contains, values)
            if expected not in actual:
                raise StepExecutionError(f"URL {actual!r} does not contain {expected!r}")
        else:
            assert step.matches is not None
            pattern = resolve_template_string(step.matches, values)
            if re.search(pattern, actual) is None:
                raise StepExecutionError(f"URL {actual!r} does not match {pattern!r}")
        return "URL assertion passed", {"url": actual}

    if isinstance(step, BrowserAssertValueStep):
        locator = _locator(page, step.target)
        actual = locator.input_value(timeout=timeout)
        if step.equals is not None:
            expected = resolve_template_string(step.equals, values)
            if actual != expected:
                raise StepExecutionError(f"Value was {actual!r}, expected {expected!r}")
        elif step.contains is not None:
            expected = resolve_template_string(step.contains, values)
            if expected not in actual:
                raise StepExecutionError(f"Value {actual!r} does not contain {expected!r}")
        else:
            assert step.matches is not None
            pattern = resolve_template_string(step.matches, values)
            if re.search(pattern, actual) is None:
                raise StepExecutionError(f"Value {actual!r} does not match {pattern!r}")
        return "Value assertion passed", {"value": actual}

    if isinstance(step, BrowserAssertCountStep):
        count = _locator(page, step.target).count()
        if step.equals is not None and count != step.equals:
            raise StepExecutionError(f"Element count was {count}, expected {step.equals}")
        if step.minimum is not None and count < step.minimum:
            raise StepExecutionError(f"Element count was {count}, minimum is {step.minimum}")
        if step.maximum is not None and count > step.maximum:
            raise StepExecutionError(f"Element count was {count}, maximum is {step.maximum}")
        return "Count assertion passed", {"count": count}

    if isinstance(step, BrowserScreenshotStep):
        relative = runtime.flow_dir / f"manual-{safe_slug(step.name)}.png"
        page.screenshot(path=str(relative), full_page=step.full_page)
        return "Screenshot captured", {"artifact_path": str(relative)}

    if isinstance(step, BrowserExtractStep):
        locator = _locator(page, step.target)
        value = (
            locator.get_attribute(step.attribute)
            if step.attribute
            else locator.inner_text(timeout=timeout)
        )
        if value is None:
            raise StepExecutionError("Extracted value is null")
        runtime.state.context_values[step.variable] = value
        return f"Extracted value into {step.variable}", {"variable": step.variable, "value": value}

    if isinstance(step, BrowserAccessibilityStep):
        details = _audit_accessibility(page, step)
        return "Accessibility baseline passed", details

    if isinstance(step, BrowserPerformanceStep):
        details = _assert_performance(page, step)
        return "Performance thresholds passed", details

    if isinstance(step, NetworkAssertStep):
        details = _network_assert(step, runtime.state, values)
        return "Network assertion passed", details

    if isinstance(step, HttpPollStep):
        started = time.perf_counter()
        last_error = "poll did not run"
        attempts = 0
        while _elapsed_ms(started) <= step.poll_timeout_ms:
            attempts += 1
            response, duration_ms, resolved = _http_request(step, contract, values, http_client)
            try:
                _assert_http(
                    response, HttpAssertions.model_validate(resolved["assertions"]), duration_ms
                )
                if step.save_json_as:
                    runtime.state.context_values[step.save_json_as] = response.json()
                return "HTTP poll assertion passed", {
                    "url": resolved["url"],
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                    "attempts": attempts,
                }
            except (StepExecutionError, ValueError) as error:
                last_error = str(error)
                time.sleep(step.interval_ms / 1000)
        raise StepExecutionError(
            f"HTTP poll timed out after {step.poll_timeout_ms} ms: {last_error}"
        )

    if isinstance(step, HttpRequestStep):
        response, duration_ms, resolved = _http_request(step, contract, values, http_client)
        _assert_http(response, HttpAssertions.model_validate(resolved["assertions"]), duration_ms)
        if step.save_json_as:
            try:
                runtime.state.context_values[step.save_json_as] = response.json()
            except ValueError as error:
                raise StepExecutionError("save_json_as requires a JSON response") from error
        return "HTTP assertion passed", {
            "url": resolved["url"],
            "status": response.status_code,
            "duration_ms": duration_ms,
        }

    if isinstance(step, SetVariableStep):
        value = resolve_templates(step.value, values)
        runtime.state.context_values[step.variable] = value
        return f"Set variable {step.variable}", {"variable": step.variable, "value": value}

    raise StepExecutionError(f"Unsupported step type: {step.type}")


def _step_screenshot_mode(step: Step, contract: Contract) -> str:
    if step.evidence == "always":
        return "always"
    if step.evidence == "failure":
        return "failure"
    if step.evidence == "never":
        return "never"
    return contract.evidence.screenshot


def run_contract(
    contract: Contract,
    *,
    contract_path: Path,
    output_dir: Path | None = None,
    run_id: str | None = None,
) -> tuple[RunResult, Path]:
    run_started_perf = time.perf_counter()
    run_started_at = utc_iso()
    run_id = run_id or make_run_id()
    secret_values, secret_redaction_values = load_secret_environment(contract.secrets)
    if (
        secret_redaction_values
        and not contract.evidence.allow_sensitive_artifacts
        and (contract.evidence.screenshot != "never" or contract.evidence.trace != "never")
    ):
        raise ContractError(
            "Binary screenshots/traces can expose secret values. Set evidence.screenshot and "
            "evidence.trace to 'never', or explicitly set allow_sensitive_artifacts: true."
        )
    redactor = Redactor(secret_redaction_values, contract.policy.redact_patterns)
    builtins = {
        "run_id": run_id,
        "timestamp": run_started_at,
        "date": run_started_at[:10],
    }
    variables = _resolve_variables(contract.variables, builtins, secret_values)
    context_values: dict[str, Any] = {**builtins, **variables, "secret": secret_values}

    base_output = output_dir or Path(contract.evidence.output_dir)
    run_dir = base_output / run_id
    bundle = EvidenceBundle(run_dir, redactor)
    bundle.event("run.started", {"run_id": run_id, "contract": contract.name})
    bundle.write_text("contract.original.yaml", contract_path.read_text(encoding="utf-8"))
    bundle.write_json("contract.resolved.json", contract.model_dump(mode="json"))

    environment: dict[str, Any] = {
        "os": platform.platform(),
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "playwright": importlib.metadata.version("playwright"),
        "e2eproof": __version__,
        "git_commit": _git_commit(contract_path.parent),
        "cwd": str(Path.cwd()),
    }
    flow_results: list[FlowResult] = []
    policy_findings: list[str] = []

    with sync_playwright() as playwright, httpx.Client(follow_redirects=False) as http_client:
        browser = _launch_browser(playwright, contract)
        environment["browser_engine"] = contract.browser.engine
        environment["browser_version"] = browser.version
        try:
            for flow in contract.flows:
                flow_started_perf = time.perf_counter()
                flow_started_at = utc_iso()
                attempts: list[FlowAttempt] = []
                max_attempts = 1 + (
                    flow.retries if flow.retries is not None else contract.policy.retries
                )
                final_passed = False
                for attempt_number in range(1, max_attempts + 1):
                    attempt_started_perf = time.perf_counter()
                    attempt_started_at = utc_iso()
                    flow_path = Path("flows") / safe_slug(flow.id) / f"attempt-{attempt_number}"
                    flow_dir = bundle.path(flow_path)
                    flow_dir.mkdir(parents=True, exist_ok=True)
                    browser_context = _create_context(browser, contract)
                    trace_path = flow_dir / "trace.zip"
                    trace_enabled = contract.evidence.trace != "never"
                    if trace_enabled:
                        browser_context.tracing.start(
                            screenshots=True,
                            snapshots=True,
                            sources=True,
                            title=f"{flow.id} attempt {attempt_number}",
                        )
                    page = browser_context.new_page()
                    state = RuntimeState(context_values=dict(context_values))
                    state.browser_version = browser.version
                    _attach_observers(page, state, contract, redactor)
                    runtime = AttemptRuntime(
                        browser_context=browser_context,
                        page=page,
                        state=state,
                        flow_dir=flow_dir,
                        trace_temp_path=trace_path if trace_enabled else None,
                    )
                    step_results: list[StepResult] = []
                    attempt_failed = False
                    failure_message: str | None = None
                    bundle.event(
                        "flow.attempt.started",
                        {"flow": flow.id, "attempt": attempt_number, "claim": flow.claim},
                    )

                    for step_index, step in enumerate(flow.steps):
                        step_started_perf = time.perf_counter()
                        step_started_at = utc_iso()
                        step_id = step.id or f"step-{step_index + 1}"
                        baseline = (
                            len(state.console),
                            len(state.page_errors),
                            len(state.request_failures),
                            len(state.network),
                        )
                        bundle.event(
                            "step.started",
                            {
                                "flow": flow.id,
                                "attempt": attempt_number,
                                "step": step_id,
                                "type": step.type,
                            },
                        )
                        artifacts: list[str] = []
                        try:
                            message, details = _execute_step(
                                step,
                                runtime=runtime,
                                contract=contract,
                                http_client=http_client,
                            )
                            _check_policy(page, state, contract, baseline)
                            mode = _step_screenshot_mode(step, contract)
                            if mode == "always":
                                relative = (
                                    flow_path
                                    / f"step-{step_index + 1:03d}-{safe_slug(step.type)}.png"
                                )
                                output = bundle.path(relative)
                                page.screenshot(path=str(output), full_page=True)
                                artifacts.append(bundle.relative(output))
                            if isinstance(step, BrowserScreenshotStep):
                                manual_path = Path(details["artifact_path"])
                                if manual_path.exists():
                                    artifacts.append(bundle.relative(manual_path))
                                    details.pop("artifact_path", None)
                            step_result = StepResult(
                                index=step_index,
                                id=step_id,
                                type=step.type,
                                status="passed",
                                started_at=step_started_at,
                                finished_at=utc_iso(),
                                duration_ms=_elapsed_ms(step_started_perf),
                                message=redactor.text(message),
                                details=redactor.value(details),
                                artifacts=artifacts,
                                attempt=attempt_number,
                            )
                            bundle.event(
                                "step.finished",
                                {
                                    "flow": flow.id,
                                    "attempt": attempt_number,
                                    "step": step_id,
                                    "status": "passed",
                                    "duration_ms": step_result.duration_ms,
                                },
                            )
                        except (
                            E2EProofError,
                            PlaywrightTimeoutError,
                            PlaywrightError,
                            httpx.HTTPError,
                            re.error,
                            ValueError,
                        ) as error:
                            message = redactor.text(str(error))
                            mode = _step_screenshot_mode(step, contract)
                            if mode in {"always", "failure"}:
                                try:
                                    relative = flow_path / f"step-{step_index + 1:03d}-failure.png"
                                    output = bundle.path(relative)
                                    page.screenshot(path=str(output), full_page=True)
                                    artifacts.append(bundle.relative(output))
                                except PlaywrightError:
                                    pass
                            step_result = StepResult(
                                index=step_index,
                                id=step_id,
                                type=step.type,
                                status="failed",
                                started_at=step_started_at,
                                finished_at=utc_iso(),
                                duration_ms=_elapsed_ms(step_started_perf),
                                message=message,
                                details={"error_type": type(error).__name__, "url": page.url},
                                artifacts=artifacts,
                                attempt=attempt_number,
                            )
                            attempt_failed = True
                            failure_message = f"{step_id} ({step.type}): {message}"
                            bundle.event(
                                "step.finished",
                                {
                                    "flow": flow.id,
                                    "attempt": attempt_number,
                                    "step": step_id,
                                    "status": "failed",
                                    "error": message,
                                    "duration_ms": step_result.duration_ms,
                                },
                            )
                        step_results.append(step_result)
                        if step_result.status == "failed" and not step.continue_on_failure:
                            break

                    try:
                        if contract.evidence.include_console:
                            bundle.write_json(flow_path / "console.json", state.console)
                        if contract.evidence.include_network:
                            network_data = []
                            for record in state.network:
                                item = {
                                    "kind": record.kind,
                                    "url": record.url,
                                    "method": record.method,
                                    "status": record.status,
                                    "resource_type": record.resource_type,
                                    "failure": record.failure,
                                    "content_type": record.content_type,
                                    "timestamp": record.timestamp,
                                }
                                if contract.evidence.include_response_bodies:
                                    item["request_body"] = record.request_body
                                    item["response_body"] = record.response_body
                                network_data.append(item)
                            bundle.write_json(flow_path / "network.json", network_data)
                        if contract.evidence.include_page_html:
                            bundle.write_text(flow_path / "page.html", page.content())
                    except PlaywrightError:
                        pass

                    if trace_enabled:
                        try:
                            browser_context.tracing.stop(path=str(trace_path))
                            keep_trace = contract.evidence.trace == "always" or (
                                contract.evidence.trace == "failure" and attempt_failed
                            )
                            if not keep_trace and trace_path.exists():
                                trace_path.unlink()
                        except PlaywrightError as error:
                            policy_findings.append(
                                redactor.text(f"Could not finalize trace for {flow.id}: {error}")
                            )
                    browser_context.close()

                    attempt = FlowAttempt(
                        attempt=attempt_number,
                        status="failed" if attempt_failed else "passed",
                        started_at=attempt_started_at,
                        finished_at=utc_iso(),
                        duration_ms=_elapsed_ms(attempt_started_perf),
                        steps=step_results,
                        failure=failure_message,
                    )
                    attempts.append(attempt)
                    bundle.event(
                        "flow.attempt.finished",
                        {
                            "flow": flow.id,
                            "attempt": attempt_number,
                            "status": attempt.status,
                            "duration_ms": attempt.duration_ms,
                        },
                    )
                    if not attempt_failed:
                        final_passed = True
                        break

                if final_passed and len(attempts) == 1:
                    flow_status = "passed"
                elif final_passed:
                    flow_status = "flaky"
                    if contract.policy.fail_on_flaky:
                        policy_findings.append(
                            f"Flow {flow.id} was flaky and fail_on_flaky is enabled"
                        )
                else:
                    flow_status = "failed"
                flow_result = FlowResult(
                    id=flow.id,
                    claim=flow.claim,
                    status=flow_status,
                    started_at=flow_started_at,
                    finished_at=utc_iso(),
                    duration_ms=_elapsed_ms(flow_started_perf),
                    attempts=attempts,
                    tags=flow.tags,
                )
                flow_results.append(flow_result)
        finally:
            browser.close()

    failed = sum(flow.status == "failed" for flow in flow_results)
    flaky = sum(flow.status == "flaky" for flow in flow_results)
    passed = sum(flow.status == "passed" for flow in flow_results)
    skipped = sum(flow.status == "skipped" for flow in flow_results)
    run_status = (
        "failed"
        if failed or (flaky and contract.policy.fail_on_flaky) or policy_findings
        else ("flaky" if flaky else "passed")
    )
    summary = {
        "flows": len(flow_results),
        "passed": passed,
        "failed": failed,
        "flaky": flaky,
        "skipped": skipped,
        "steps": sum(len(attempt.steps) for flow in flow_results for attempt in flow.attempts),
    }
    result = RunResult(
        product_version=__version__,
        run_id=run_id,
        contract_name=contract.name,
        contract_path=str(contract_path),
        contract_sha256=sha256_file(contract_path),
        status=run_status,
        started_at=run_started_at,
        finished_at=utc_iso(),
        duration_ms=_elapsed_ms(run_started_perf),
        environment=environment,
        flows=flow_results,
        summary=summary,
        policy_findings=policy_findings,
    )

    bundle.event("run.finished", {"status": result.status, "summary": summary})
    sign_key = Path(contract.evidence.sign_key) if contract.evidence.sign_key else None
    result.integrity = {
        "manifest": "manifest.json",
        "signature": "signature.json" if sign_key else None,
        "signed": bool(sign_key),
        "event_log": "events.jsonl",
    }
    bundle.write_json("result.json", result.model_dump(mode="json"))
    bundle.write_text("report.html", generate_html_report(result), redact=False)
    write_junit(result, bundle.path("junit.xml"))
    bundle.finalize(sign_key=sign_key)
    return result, run_dir
