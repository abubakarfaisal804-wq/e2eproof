from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import socket
import string
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from .errors import ContractError, StepExecutionError

_TEMPLATE_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*\}\}")


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_iso() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def make_run_id() -> str:
    stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    suffix = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6))
    return f"{stamp}-{suffix}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def safe_slug(value: str, *, fallback: str = "item") -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip(".-")
    return slug[:100] or fallback


def safe_join(root: Path, relative: str | Path) -> Path:
    candidate = (root / relative).resolve()
    root_resolved = root.resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ContractError(f"Artifact path escapes output directory: {relative}")
    return candidate


def flatten_context(value: Any, prefix: str = "") -> dict[str, Any]:
    output: dict[str, Any] = {}
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            output.update(flatten_context(child, child_prefix))
    else:
        output[prefix] = value
    return output


def resolve_template_string(value: str, context: Mapping[str, Any]) -> str:
    flattened = flatten_context(context)

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in flattened:
            raise ContractError(f"Unknown template variable: {key}")
        resolved = flattened[key]
        if resolved is None:
            return ""
        if isinstance(resolved, (dict, list)):
            return json.dumps(resolved, ensure_ascii=False)
        return str(resolved)

    return _TEMPLATE_RE.sub(replace, value)


def resolve_templates(value: Any, context: Mapping[str, Any]) -> Any:
    if isinstance(value, str):
        return resolve_template_string(value, context)
    if isinstance(value, list):
        return [resolve_templates(item, context) for item in value]
    if isinstance(value, tuple):
        return tuple(resolve_templates(item, context) for item in value)
    if isinstance(value, dict):
        return {str(key): resolve_templates(item, context) for key, item in value.items()}
    return value


def json_path_get(value: Any, path: str) -> tuple[bool, Any]:
    """Small deterministic JSON path implementation: $.a.b[0].c."""
    if path == "$":
        return True, value
    if not path.startswith("$."):
        raise StepExecutionError(f"Unsupported JSON path: {path}")

    tokens: list[str | int] = []
    cursor = path[2:]
    token = ""
    index = 0
    while index < len(cursor):
        char = cursor[index]
        if char == ".":
            if not token:
                raise StepExecutionError(f"Invalid JSON path: {path}")
            tokens.append(token)
            token = ""
            index += 1
            continue
        if char == "[":
            if token:
                tokens.append(token)
                token = ""
            end = cursor.find("]", index)
            if end == -1:
                raise StepExecutionError(f"Invalid JSON path: {path}")
            raw_index = cursor[index + 1 : end]
            if not raw_index.isdigit():
                raise StepExecutionError(f"Only numeric JSON indexes are supported: {path}")
            tokens.append(int(raw_index))
            index = end + 1
            if index < len(cursor) and cursor[index] == ".":
                index += 1
            continue
        token += char
        index += 1
    if token:
        tokens.append(token)

    current = value
    for item in tokens:
        if isinstance(item, int):
            if not isinstance(current, Sequence) or isinstance(current, (str, bytes)):
                return False, None
            if item >= len(current):
                return False, None
            current = current[item]
        else:
            if not isinstance(current, Mapping) or item not in current:
                return False, None
            current = current[item]
    return True, current


def normalize_text(value: str) -> str:
    return " ".join(value.split())


def compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error as error:
            raise ContractError(f"Invalid regular expression {pattern!r}: {error}") from error
    return compiled


class Redactor:
    def __init__(self, secrets_to_redact: list[str], patterns: list[str] | None = None) -> None:
        self._secrets = sorted(
            {secret for secret in secrets_to_redact if secret and len(secret) >= 3},
            key=len,
            reverse=True,
        )
        self._patterns = compile_patterns(patterns or [])

    def text(self, value: str) -> str:
        redacted = value
        for secret_value in self._secrets:
            redacted = redacted.replace(secret_value, "[REDACTED]")
        for pattern in self._patterns:
            redacted = pattern.sub("[REDACTED]", redacted)
        return redacted

    def value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.value(item) for item in value]
        if isinstance(value, tuple):
            return [self.value(item) for item in value]
        if isinstance(value, dict):
            return {str(key): self.value(item) for key, item in value.items()}
        return value


def load_secret_environment(secret_specs: Mapping[str, Any]) -> tuple[dict[str, str], list[str]]:
    resolved: dict[str, str] = {}
    values: list[str] = []
    for name, spec in secret_specs.items():
        env_name = spec.env
        env_value = os.getenv(env_name)
        if env_value is None:
            if spec.required:
                raise ContractError(f"Required secret environment variable is missing: {env_name}")
            env_value = ""
        resolved[name] = env_value
        if env_value:
            values.append(env_value)
    return resolved, values


def resolve_url(base_url: str, value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme:
        return value
    return urljoin(base_url.rstrip("/") + "/", value)


def validate_url_allowed(
    url: str,
    *,
    base_url: str,
    allowed_hosts: Sequence[str],
    allowed_schemes: Sequence[str],
) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in allowed_schemes:
        raise ContractError(f"URL scheme is not allowed: {parsed.scheme or '(missing)'}")
    if parsed.username or parsed.password:
        raise ContractError("Credentials in URLs are not allowed")
    if not parsed.hostname:
        raise ContractError(f"URL has no hostname: {url}")

    base_host = urlparse(base_url).hostname
    allowed = {host.lower() for host in allowed_hosts}
    if base_host:
        allowed.add(base_host.lower())
    if parsed.hostname.lower() not in allowed:
        raise ContractError(
            f"Host {parsed.hostname!r} is outside the contract allowlist: {sorted(allowed)}"
        )


def host_resolves(host: str) -> bool:
    try:
        socket.getaddrinfo(host, None)
    except OSError:
        return False
    return True
