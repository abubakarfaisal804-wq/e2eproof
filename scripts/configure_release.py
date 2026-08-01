from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OWNER_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


def replace_owner(path: Path, owner: str) -> bool:
    text = path.read_text(encoding="utf-8")
    updated = text.replace("OWNER", owner)
    if updated == text:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def configure_pyproject(owner: str) -> bool:
    path = ROOT / "pyproject.toml"
    text = path.read_text(encoding="utf-8")
    block = f'''\n[project.urls]\nHomepage = "https://github.com/{owner}/e2eproof"\nDocumentation = "https://github.com/{owner}/e2eproof#readme"\nRepository = "https://github.com/{owner}/e2eproof"\nIssues = "https://github.com/{owner}/e2eproof/issues"\n'''
    if "[project.urls]" in text:
        start = text.index("[project.urls]")
        next_section = text.find("\n[", start + 1)
        end = len(text) if next_section == -1 else next_section
        updated = text[:start] + block.lstrip("\n") + text[end:]
    else:
        marker = "\n[project.optional-dependencies]"
        if marker not in text:
            raise RuntimeError("Could not find insertion point in pyproject.toml")
        updated = text.replace(marker, block + marker, 1)
    if updated == text:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure owner-specific public release metadata.")
    parser.add_argument("--owner", required=True, help="GitHub user or organization name")
    args = parser.parse_args()
    owner = args.owner.strip()
    if not OWNER_PATTERN.fullmatch(owner):
        parser.error("Invalid GitHub owner name")

    changed: list[str] = []
    for relative in [
        Path("README.md"),
        Path(".github/ISSUE_TEMPLATE/config.yml"),
        Path("RELEASE_SETUP.md"),
    ]:
        path = ROOT / relative
        if replace_owner(path, owner):
            changed.append(str(relative))
    if configure_pyproject(owner):
        changed.append("pyproject.toml")

    print(f"Configured repository owner: {owner}")
    print("Changed: " + (", ".join(changed) if changed else "nothing; already configured"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
