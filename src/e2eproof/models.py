from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class LocatorSpec(StrictModel):
    css: str | None = None
    role: str | None = None
    name: str | None = None
    text: str | None = None
    label: str | None = None
    placeholder: str | None = None
    test_id: str | None = None
    nth: int | None = None
    exact: bool = False

    @model_validator(mode="after")
    def exactly_one_strategy(self) -> LocatorSpec:
        strategies = [
            self.css,
            self.role,
            self.text,
            self.label,
            self.placeholder,
            self.test_id,
        ]
        if sum(value is not None for value in strategies) != 1:
            raise ValueError(
                "A locator must define exactly one of css, role, text, label, placeholder, or test_id"
            )
        if self.role is None and self.name is not None:
            raise ValueError("locator.name can only be used together with locator.role")
        return self


Target: TypeAlias = str | LocatorSpec


class BaseStep(StrictModel):
    id: str | None = None
    type: str
    timeout_ms: int | None = Field(default=None, ge=100, le=300_000)
    continue_on_failure: bool = False
    evidence: Literal["auto", "always", "failure", "never"] = "auto"


class BrowserGotoStep(BaseStep):
    type: Literal["browser.goto"]
    url: str
    wait_until: Literal["commit", "domcontentloaded", "load", "networkidle"] = "load"


class BrowserFillStep(BaseStep):
    type: Literal["browser.fill"]
    target: Target
    value: str


class BrowserClickStep(BaseStep):
    type: Literal["browser.click"]
    target: Target
    button: Literal["left", "right", "middle"] = "left"
    click_count: int = Field(default=1, ge=1, le=3)


class BrowserPressStep(BaseStep):
    type: Literal["browser.press"]
    key: str
    target: Target | None = None


class BrowserSelectStep(BaseStep):
    type: Literal["browser.select"]
    target: Target
    value: str | list[str]


class BrowserCheckStep(BaseStep):
    type: Literal["browser.check"]
    target: Target
    checked: bool = True


class BrowserWaitStep(BaseStep):
    type: Literal["browser.wait"]
    target: Target | None = None
    state: Literal["attached", "detached", "visible", "hidden"] = "visible"
    milliseconds: int | None = Field(default=None, ge=0, le=60_000)

    @model_validator(mode="after")
    def target_or_time(self) -> BrowserWaitStep:
        if self.target is None and self.milliseconds is None:
            raise ValueError("browser.wait requires target or milliseconds")
        if self.target is not None and self.milliseconds is not None:
            raise ValueError("browser.wait accepts target or milliseconds, not both")
        return self


class BrowserAssertTextStep(BaseStep):
    type: Literal["browser.assert_text"]
    target: Target | None = None
    equals: str | None = None
    contains: str | None = None
    not_contains: str | None = None
    matches: str | None = None
    normalize_whitespace: bool = True

    @model_validator(mode="after")
    def exactly_one_assertion(self) -> BrowserAssertTextStep:
        values = [self.equals, self.contains, self.not_contains, self.matches]
        if sum(value is not None for value in values) != 1:
            raise ValueError("browser.assert_text requires exactly one assertion")
        return self


class BrowserAssertVisibleStep(BaseStep):
    type: Literal["browser.assert_visible"]
    target: Target
    visible: bool = True


class BrowserAssertUrlStep(BaseStep):
    type: Literal["browser.assert_url"]
    equals: str | None = None
    contains: str | None = None
    matches: str | None = None

    @model_validator(mode="after")
    def exactly_one_assertion(self) -> BrowserAssertUrlStep:
        values = [self.equals, self.contains, self.matches]
        if sum(value is not None for value in values) != 1:
            raise ValueError("browser.assert_url requires exactly one assertion")
        return self


class BrowserAssertValueStep(BaseStep):
    type: Literal["browser.assert_value"]
    target: Target
    equals: str | None = None
    contains: str | None = None
    matches: str | None = None

    @model_validator(mode="after")
    def exactly_one_assertion(self) -> BrowserAssertValueStep:
        values = [self.equals, self.contains, self.matches]
        if sum(value is not None for value in values) != 1:
            raise ValueError("browser.assert_value requires exactly one assertion")
        return self


class BrowserAssertCountStep(BaseStep):
    type: Literal["browser.assert_count"]
    target: Target
    equals: int | None = Field(default=None, ge=0)
    minimum: int | None = Field(default=None, ge=0)
    maximum: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def valid_bounds(self) -> BrowserAssertCountStep:
        if self.equals is None and self.minimum is None and self.maximum is None:
            raise ValueError("browser.assert_count requires equals, minimum, or maximum")
        if self.equals is not None and (self.minimum is not None or self.maximum is not None):
            raise ValueError("equals cannot be combined with minimum or maximum")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum cannot be greater than maximum")
        return self


class BrowserScreenshotStep(BaseStep):
    type: Literal["browser.screenshot"]
    name: str
    full_page: bool = True


class BrowserExtractStep(BaseStep):
    type: Literal["browser.extract"]
    target: Target
    variable: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$")
    attribute: str | None = None


class BrowserAccessibilityStep(BaseStep):
    type: Literal["browser.audit_accessibility"]
    require_title: bool = True
    require_html_lang: bool = True
    require_image_alt: bool = True
    require_control_names: bool = True
    require_button_names: bool = True
    maximum_violations: int = Field(default=0, ge=0)


class BrowserPerformanceStep(BaseStep):
    type: Literal["browser.assert_performance"]
    max_dom_content_loaded_ms: int | None = Field(default=None, ge=1)
    max_load_ms: int | None = Field(default=None, ge=1)
    max_transfer_bytes: int | None = Field(default=None, ge=1)


class NetworkAssertStep(BaseStep):
    type: Literal["network.assert"]
    kind: Literal["request", "response", "either"] = "either"
    url_contains: str | None = None
    url_matches: str | None = None
    method: str | None = None
    status: int | None = Field(default=None, ge=100, le=599)
    body_contains: str | None = None
    body_not_contains: str | None = None
    minimum: int = Field(default=1, ge=0)
    maximum: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def valid_matcher(self) -> NetworkAssertStep:
        if self.url_contains is None and self.url_matches is None:
            raise ValueError("network.assert requires url_contains or url_matches")
        if self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("network.assert minimum cannot be greater than maximum")
        return self


class JsonAssertion(StrictModel):
    path: str = Field(pattern=r"^\$($|\.)")
    equals: Any | None = None
    not_equals: Any | None = None
    contains: Any | None = None
    exists: bool | None = None
    matches: str | None = None

    @model_validator(mode="after")
    def exactly_one_assertion(self) -> JsonAssertion:
        values = [self.equals, self.not_equals, self.contains, self.exists, self.matches]
        if sum(value is not None for value in values) != 1:
            raise ValueError("JSON assertion requires exactly one assertion operator")
        return self


class HttpAssertions(StrictModel):
    status: int | list[int] | None = None
    header_equals: dict[str, str] = Field(default_factory=dict)
    header_contains: dict[str, str] = Field(default_factory=dict)
    body_contains: str | None = None
    body_not_contains: str | None = None
    body_matches: str | None = None
    json_assertions: list[JsonAssertion] = Field(default_factory=list, alias="json", serialization_alias="json")
    max_duration_ms: int | None = Field(default=None, ge=1)


class HttpRequestStep(BaseStep):
    type: Literal["http.request"]
    name: str | None = None
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"] = "GET"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    params: dict[str, str] = Field(default_factory=dict)
    json_body: Any | None = None
    body: str | None = None
    save_json_as: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$")
    assertions: HttpAssertions = Field(default_factory=HttpAssertions)

    @model_validator(mode="after")
    def body_exclusive(self) -> HttpRequestStep:
        if self.json_body is not None and self.body is not None:
            raise ValueError("http.request accepts json_body or body, not both")
        return self


class HttpPollStep(HttpRequestStep):
    type: Literal["http.poll"]
    interval_ms: int = Field(default=500, ge=50, le=30_000)
    poll_timeout_ms: int = Field(default=10_000, ge=100, le=300_000)


class SetVariableStep(BaseStep):
    type: Literal["set.variable"]
    variable: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$")
    value: Any


Step = Annotated[
    BrowserGotoStep
    | BrowserFillStep
    | BrowserClickStep
    | BrowserPressStep
    | BrowserSelectStep
    | BrowserCheckStep
    | BrowserWaitStep
    | BrowserAssertTextStep
    | BrowserAssertVisibleStep
    | BrowserAssertUrlStep
    | BrowserAssertValueStep
    | BrowserAssertCountStep
    | BrowserScreenshotStep
    | BrowserExtractStep
    | BrowserAccessibilityStep
    | BrowserPerformanceStep
    | NetworkAssertStep
    | HttpRequestStep
    | HttpPollStep
    | SetVariableStep,
    Field(discriminator="type"),
]


class Flow(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    claim: str = Field(min_length=5, max_length=500)
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    steps: list[Step] = Field(min_length=1)
    retries: int | None = Field(default=None, ge=0, le=5)


class SecretRef(StrictModel):
    env: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    required: bool = True


class BrowserConfig(StrictModel):
    engine: Literal["chromium", "firefox", "webkit"] = "chromium"
    headless: bool = True
    executable_path: str | None = None
    channel: str | None = None
    viewport_width: int = Field(default=1280, ge=320, le=7680)
    viewport_height: int = Field(default=720, ge=240, le=4320)
    locale: str = "en-US"
    timezone_id: str | None = None
    color_scheme: Literal["light", "dark", "no-preference"] = "light"
    ignore_https_errors: bool = False
    user_agent: str | None = None


class EvidenceConfig(StrictModel):
    output_dir: str = "evidence"
    screenshot: Literal["always", "failure", "never"] = "failure"
    trace: Literal["always", "failure", "never"] = "failure"
    include_console: bool = True
    include_network: bool = True
    include_response_bodies: bool = False
    max_response_body_bytes: int = Field(default=65_536, ge=0, le=5_000_000)
    include_page_html: bool = False
    sign_key: str | None = None
    allow_sensitive_artifacts: bool = False


class PolicyConfig(StrictModel):
    timeout_ms: int = Field(default=10_000, ge=100, le=300_000)
    navigation_timeout_ms: int = Field(default=30_000, ge=100, le=300_000)
    retries: int = Field(default=0, ge=0, le=5)
    allowed_hosts: list[str] = Field(default_factory=list)
    allowed_schemes: list[Literal["http", "https"]] = Field(default_factory=lambda: ["http", "https"])
    fail_on_console_error: bool = True
    fail_on_page_error: bool = True
    fail_on_request_failure: bool = True
    console_error_ignore: list[str] = Field(default_factory=list)
    request_failure_ignore: list[str] = Field(default_factory=list)
    forbidden_visible_markers: list[str] = Field(default_factory=list)
    forbidden_network_markers: list[str] = Field(default_factory=list)
    redact_patterns: list[str] = Field(default_factory=list)
    fail_on_flaky: bool = False
    enforce_browser_host_allowlist: bool = True


class Contract(StrictModel):
    version: Literal[1, "1"] = 1
    name: str = Field(min_length=3, max_length=120)
    description: str | None = None
    base_url: str
    variables: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, SecretRef] = Field(default_factory=dict)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    evidence: EvidenceConfig = Field(default_factory=EvidenceConfig)
    flows: list[Flow] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_flow_ids(self) -> Contract:
        ids = [flow.id for flow in self.flows]
        if len(ids) != len(set(ids)):
            raise ValueError("Flow IDs must be unique")
        return self
