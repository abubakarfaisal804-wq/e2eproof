from __future__ import annotations

from pathlib import Path

import pytest

from e2eproof.errors import ContractError, StepExecutionError
from e2eproof.utils import (
    Redactor,
    json_path_get,
    resolve_template_string,
    safe_join,
    safe_slug,
    validate_url_allowed,
)


def test_template_and_json_path() -> None:
    context = {"user": {"email": "a@example.com"}, "items": [1, 2]}
    assert resolve_template_string("x={{user.email}}", context) == "x=a@example.com"
    assert json_path_get({"a": [{"b": 3}]}, "$.a[0].b") == (True, 3)
    assert json_path_get({"a": []}, "$.a[0]") == (False, None)
    with pytest.raises(ContractError, match="Unknown template"):
        resolve_template_string("{{missing}}", context)
    with pytest.raises(StepExecutionError, match="numeric"):
        json_path_get({"a": []}, "$.a[x]")


def test_redaction_nested_and_regex() -> None:
    redactor = Redactor(["super-secret"], [r"token-[0-9]+"])
    value = {"x": "super-secret token-123", "items": ["ok", "super-secret"]}
    assert redactor.value(value) == {
        "x": "[REDACTED] [REDACTED]",
        "items": ["ok", "[REDACTED]"],
    }


def test_safe_paths_and_slug(tmp_path: Path) -> None:
    assert safe_slug("../bad name") == "bad-name"
    assert safe_join(tmp_path, "a/b.txt").parent.name == "a"
    with pytest.raises(ContractError, match="escapes"):
        safe_join(tmp_path, "../escape")


def test_url_allowlist() -> None:
    validate_url_allowed(
        "https://app.example.com/x",
        base_url="https://app.example.com",
        allowed_hosts=[],
        allowed_schemes=["https"],
    )
    with pytest.raises(ContractError, match="outside"):
        validate_url_allowed(
            "https://evil.example/x",
            base_url="https://app.example.com",
            allowed_hosts=[],
            allowed_schemes=["https"],
        )
    with pytest.raises(ContractError, match="Credentials"):
        validate_url_allowed(
            "https://user:pass@app.example.com/x",
            base_url="https://app.example.com",
            allowed_hosts=[],
            allowed_schemes=["https"],
        )
    with pytest.raises(ContractError, match="scheme"):
        validate_url_allowed(
            "http://app.example.com/x",
            base_url="https://app.example.com",
            allowed_hosts=[],
            allowed_schemes=["https"],
        )


def test_more_utils_branches(monkeypatch) -> None:
    from e2eproof.models import SecretRef
    from e2eproof.utils import (
        compile_patterns,
        load_secret_environment,
        resolve_templates,
        resolve_url,
    )

    assert resolve_templates(["{{x}}", {"y": "{{x}}"}], {"x": 7}) == ["7", {"y": "7"}]
    assert resolve_url("https://example.com/base", "/x") == "https://example.com/x"
    assert compile_patterns(["abc"])[0].search("ABC")
    with pytest.raises(ContractError, match="Invalid regular"):
        compile_patterns(["["])
    monkeypatch.setenv("TOKEN_X", "secret")
    values, redactions = load_secret_environment({"token": SecretRef(env="TOKEN_X")})
    assert values["token"] == "secret" and redactions == ["secret"]
    monkeypatch.delenv("MISSING_X", raising=False)
    with pytest.raises(ContractError, match="missing"):
        load_secret_environment({"token": SecretRef(env="MISSING_X")})
    values, redactions = load_secret_environment(
        {"token": SecretRef(env="MISSING_X", required=False)}
    )
    assert values["token"] == "" and redactions == []
