from __future__ import annotations

from pathlib import Path

import pytest

from e2eproof.errors import ContractError
from e2eproof.utils import safe_join, safe_slug, validate_url_allowed


@pytest.mark.parametrize("scheme", ["file", "data", "javascript", "ftp", "ws", "gopher"])
def test_non_http_schemes_fail_closed(scheme: str) -> None:
    with pytest.raises(ContractError):
        validate_url_allowed(
            f"{scheme}://app.example.com/resource",
            base_url="https://app.example.com",
            allowed_hosts=[],
            allowed_schemes=["https"],
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/resource",
        "https://app.example.com.evil.example/resource",
        "https://evil-app.example.com/resource",
        "https://app.example.com@evil.example/resource",
        "https://user:secret@app.example.com/resource",
    ],
)
def test_host_confusion_and_credentials_are_rejected(url: str) -> None:
    with pytest.raises(ContractError):
        validate_url_allowed(
            url,
            base_url="https://app.example.com",
            allowed_hosts=[],
            allowed_schemes=["https"],
        )


@pytest.mark.parametrize("relative", ["../x", "../../x", "/tmp/x", "a/../../../x"])
def test_artifact_traversal_is_rejected(tmp_path: Path, relative: str) -> None:
    with pytest.raises(ContractError):
        safe_join(tmp_path, relative)


def test_generated_slugs_never_contain_path_separators() -> None:
    for value in ["../secret", "a/b", r"a\\b", "..", "/absolute", "a:b"]:
        slug = safe_slug(value)
        assert "/" not in slug
        assert "\\" not in slug
        assert slug not in {"", ".", ".."}
