from __future__ import annotations

import ast
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

import yaml

ROOT = Path(__file__).resolve().parents[1]
PYTHON_DIRS = [ROOT / "src", ROOT / "tests", ROOT / "demo", ROOT / "scripts"]
TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".toml", ".html", ".txt", ".sh", ".bat"}
SECRET_PATTERNS = [
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?:ghp|github_pat)_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]


class HTMLAudit(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.html_seen = False
        self.title_seen = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "html":
            self.html_seen = True
        if tag == "title":
            self.title_seen = True


def iter_files(roots: Iterable[Path], suffix: str) -> Iterable[Path]:
    for root in roots:
        if root.exists():
            yield from root.rglob(f"*{suffix}")


def call_name(node: ast.Call) -> str:
    target = node.func
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        parts = [target.attr]
        value = target.value
        while isinstance(value, ast.Attribute):
            parts.append(value.attr)
            value = value.value
        if isinstance(value, ast.Name):
            parts.append(value.id)
        return ".".join(reversed(parts))
    return ""


def audit_python(path: Path, errors: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as error:
        errors.append(f"{path}: syntax error: {error}")
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names):
            errors.append(f"{path}:{node.lineno}: wildcard import")
        if not isinstance(node, ast.Call):
            continue
        name = call_name(node)
        if name in {"eval", "exec"}:
            errors.append(f"{path}:{node.lineno}: dangerous call {name}")
        if name in {"pickle.load", "pickle.loads", "marshal.loads"}:
            errors.append(f"{path}:{node.lineno}: unsafe deserialization {name}")
        if name in {"yaml.load", "yaml.unsafe_load"}:
            errors.append(f"{path}:{node.lineno}: unsafe YAML loading {name}")
        if name.startswith("subprocess."):
            for keyword in node.keywords:
                if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                    errors.append(f"{path}:{node.lineno}: subprocess shell=True")


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    for path in iter_files(PYTHON_DIRS, ".py"):
        audit_python(path, errors)

    ignored = {"coverage.json"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES or path.name in ignored:
            continue
        if any(part in {".venv", "build", "dist", "evidence", "sample_output", ".pytest_cache"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            errors.append(f"{path}: not valid UTF-8")
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            if line.rstrip(" \t") != line:
                warnings.append(f"{path}:{line_number}: trailing whitespace")
        if "tests" not in path.parts:
            for pattern in SECRET_PATTERNS:
                if pattern.search(text):
                    errors.append(f"{path}: likely literal credential")

    for path in list(ROOT.rglob("*.yaml")) + list(ROOT.rglob("*.yml")):
        if any(part in {".venv", "build", "dist"} for part in path.parts):
            continue
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as error:
            errors.append(f"{path}: invalid YAML: {error}")

    for path in ROOT.rglob("*.json"):
        if any(part in {".venv", "build", "dist", "sample_output"} for part in path.parts):
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as error:
            errors.append(f"{path}: invalid JSON: {error}")

    for path in ROOT.rglob("*.html"):
        if any(part in {".venv", "build", "dist"} for part in path.parts):
            continue
        parser = HTMLAudit()
        try:
            parser.feed(path.read_text(encoding="utf-8"))
        except Exception as error:
            errors.append(f"{path}: invalid HTML parser input: {error}")
            continue
        if not parser.html_seen or not parser.title_seen:
            errors.append(f"{path}: missing html or title element")

    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    print(
        f"Static audit: {len(errors)} errors, {len(warnings)} warnings, "
        f"{sum(1 for _ in iter_files(PYTHON_DIRS, '.py'))} Python files checked."
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
