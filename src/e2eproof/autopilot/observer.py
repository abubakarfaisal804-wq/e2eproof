from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import JsonValue, TypeAdapter

from .errors import AutopilotError
from .schemas import BudgetConfig, FactKind, Observation

_REPOSITORY_SLUG = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_JSON_ADAPTER: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


@dataclass(frozen=True)
class ObservationReport:
    observations: list[Observation]
    complete: bool
    errors: list[str]
    api_requests: int


@dataclass(frozen=True)
class APIUnavailable:
    status_code: int


def _run_git(root: Path, arguments: list[str], timeout_seconds: float) -> str:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise AutopilotError(f"Read-only git observation failed: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip()[:500]
        raise AutopilotError(f"Read-only git observation failed: {detail}")
    return completed.stdout.strip()


def _file_digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def observe_local_repository(
    root: Path,
    *,
    now: datetime,
    process_timeout_seconds: float,
) -> list[Observation]:
    repository = root.resolve()
    head = _run_git(repository, ["rev-parse", "HEAD"], process_timeout_seconds)
    branch = _run_git(repository, ["branch", "--show-current"], process_timeout_seconds)
    dirty = bool(_run_git(repository, ["status", "--porcelain"], process_timeout_seconds))
    dependency_files: dict[str, JsonValue] = {
        name: _file_digest(repository / name)
        for name in ("pyproject.toml", "requirements.txt", "requirements-dev.txt")
    }
    project_version: str | None = None
    pyproject_path = repository / "pyproject.toml"
    if pyproject_path.is_file():
        try:
            raw = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
            project = raw.get("project", {})
            if isinstance(project, dict) and isinstance(project.get("version"), str):
                project_version = project["version"]
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise AutopilotError(f"Could not inspect pyproject.toml: {error}") from error
    return [
        Observation(
            observation_id="local.repository",
            observed_at=now,
            kind=FactKind.VERIFIED,
            category="repository",
            source="local git",
            summary="Observed the local repository head, branch, and cleanliness.",
            value={"head": head, "branch": branch, "dirty": dirty},
        ),
        Observation(
            observation_id="local.dependency_state",
            observed_at=now,
            kind=FactKind.VERIFIED,
            category="dependencies",
            source="tracked dependency manifests",
            summary="Recorded dependency-manifest hashes and package version without resolving packages.",
            value={"files": dependency_files, "project_version": project_version},
        ),
    ]


class GitHubObserver:
    """Bounded read-only GitHub REST observer. It never sends a mutating request."""

    def __init__(
        self,
        *,
        repository: str,
        token: str,
        budgets: BudgetConfig,
        transport: httpx.BaseTransport | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not _REPOSITORY_SLUG.fullmatch(repository):
            raise AutopilotError("GitHub repository must use owner/name format")
        if not token:
            raise AutopilotError("A GitHub token is required for live read-only observation")
        self.repository = repository
        self.token = token
        self.budgets = budgets
        self.transport = transport
        self.sleeper = sleeper
        self.request_count = 0

    def _get(
        self,
        client: httpx.Client,
        path: str,
        *,
        params: dict[str, str] | None = None,
        optional_forbidden: bool = False,
    ) -> JsonValue | APIUnavailable:
        last_error: Exception | None = None
        for attempt in range(self.budgets.api_retries + 1):
            if self.request_count >= self.budgets.api_request_limit:
                raise AutopilotError("GitHub API request budget exhausted")
            self.request_count += 1
            try:
                response = client.get(path, params=params)
            except httpx.HTTPError as error:
                last_error = error
                if attempt < self.budgets.api_retries:
                    self.sleeper(min(0.25 * (attempt + 1), 1.0))
                    continue
                raise AutopilotError(f"GitHub GET failed for {path}: {error}") from error
            if optional_forbidden and response.status_code == 403:
                return APIUnavailable(status_code=403)
            if (
                response.status_code == 429 or response.status_code >= 500
            ) and attempt < self.budgets.api_retries:
                self.sleeper(min(0.25 * (attempt + 1), 1.0))
                continue
            if response.status_code >= 400:
                raise AutopilotError(f"GitHub GET {path} returned HTTP {response.status_code}")
            try:
                payload = _JSON_ADAPTER.validate_python(response.json())
            except (json.JSONDecodeError, ValueError) as error:
                raise AutopilotError(f"GitHub GET {path} returned invalid JSON") from error
            return payload
        raise AutopilotError(f"GitHub GET failed for {path}: {last_error}")

    @staticmethod
    def _mapping(value: JsonValue | APIUnavailable, endpoint: str) -> dict[str, Any]:
        if isinstance(value, APIUnavailable) or not isinstance(value, dict):
            raise AutopilotError(f"GitHub {endpoint} response was not an object")
        return value

    @staticmethod
    def _items(value: JsonValue | APIUnavailable, endpoint: str) -> list[Any]:
        if isinstance(value, APIUnavailable) or not isinstance(value, list):
            raise AutopilotError(f"GitHub {endpoint} response was not a list")
        return value

    def observe(self, *, now: datetime) -> ObservationReport:
        observations: list[Observation] = []
        errors: list[str] = []
        base = f"/repos/{self.repository}"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        with httpx.Client(
            base_url="https://api.github.com",
            headers=headers,
            timeout=self.budgets.api_timeout_seconds,
            follow_redirects=False,
            transport=self.transport,
        ) as client:

            def get(
                name: str,
                path: str,
                *,
                params: dict[str, str] | None = None,
                optional_forbidden: bool = False,
            ) -> JsonValue | APIUnavailable | None:
                try:
                    return self._get(
                        client,
                        path,
                        params=params,
                        optional_forbidden=optional_forbidden,
                    )
                except AutopilotError as error:
                    errors.append(f"{name}: {error}")
                    return None

            repo = get("repository", base)
            branches = get("branches", f"{base}/branches", params={"per_page": "100"})
            branch_protection = get(
                "branch_protection",
                f"{base}/branches/main/protection",
                optional_forbidden=True,
            )
            pulls = get(
                "pull_requests",
                f"{base}/pulls",
                params={"state": "open", "per_page": "100"},
            )
            runs = get(
                "ci",
                f"{base}/actions/runs",
                params={"branch": "main", "per_page": "20"},
            )
            code_alerts = get(
                "code_scanning",
                f"{base}/code-scanning/alerts",
                params={"state": "open", "per_page": "100"},
                optional_forbidden=True,
            )
            secret_alerts = get(
                "secret_scanning",
                f"{base}/secret-scanning/alerts",
                params={"state": "open", "per_page": "100"},
                optional_forbidden=True,
            )
            dependabot_alerts = get(
                "dependabot",
                f"{base}/dependabot/alerts",
                params={"state": "open", "per_page": "100"},
                optional_forbidden=True,
            )
            releases = get("releases", f"{base}/releases", params={"per_page": "20"})

        if isinstance(branch_protection, APIUnavailable):
            errors.append("branch_protection: endpoint unavailable with current read token")
        if isinstance(code_alerts, APIUnavailable):
            errors.append("code_scanning: endpoint unavailable with current read token")

        if repo is not None:
            item = self._mapping(repo, "repository")
            observations.append(
                Observation(
                    observation_id="github.repository",
                    observed_at=now,
                    kind=FactKind.VERIFIED,
                    category="repository",
                    source="GitHub REST GET repository",
                    summary="Observed repository identity, visibility, and default branch.",
                    value={
                        "full_name": item.get("full_name"),
                        "visibility": item.get("visibility"),
                        "archived": item.get("archived"),
                        "default_branch": item.get("default_branch"),
                    },
                )
            )
        if branches is not None:
            normalized_branches: list[JsonValue] = []
            for item in self._items(branches, "branches"):
                if isinstance(item, dict):
                    commit = item.get("commit", {})
                    normalized_branches.append(
                        {
                            "name": item.get("name"),
                            "protected": item.get("protected"),
                            "sha": commit.get("sha") if isinstance(commit, dict) else None,
                        }
                    )
            protection_value: JsonValue = None
            if isinstance(branch_protection, APIUnavailable):
                protection_value = {
                    "available": False,
                    "status_code": branch_protection.status_code,
                }
            elif isinstance(branch_protection, dict):
                required_checks = branch_protection.get("required_status_checks", {})
                force_pushes = branch_protection.get("allow_force_pushes", {})
                deletions = branch_protection.get("allow_deletions", {})
                protection_value = {
                    "available": True,
                    "required_status_checks": (
                        {
                            "strict": required_checks.get("strict"),
                            "contexts": required_checks.get("contexts", []),
                        }
                        if isinstance(required_checks, dict)
                        else None
                    ),
                    "force_pushes_allowed": (
                        force_pushes.get("enabled") if isinstance(force_pushes, dict) else None
                    ),
                    "deletions_allowed": (
                        deletions.get("enabled") if isinstance(deletions, dict) else None
                    ),
                }
            observations.append(
                Observation(
                    observation_id="github.branches",
                    observed_at=now,
                    kind=FactKind.VERIFIED,
                    category="repository",
                    source="GitHub REST GET branches",
                    summary="Observed repository branches and default-branch protection controls.",
                    value={
                        "branches": normalized_branches,
                        "main_protection": protection_value,
                    },
                )
            )
        if pulls is not None:
            normalized_pulls: list[JsonValue] = []
            for item in self._items(pulls, "pull requests"):
                if isinstance(item, dict):
                    head = item.get("head", {})
                    normalized_pulls.append(
                        {
                            "number": item.get("number"),
                            "title": item.get("title"),
                            "draft": item.get("draft"),
                            "head": head.get("ref") if isinstance(head, dict) else None,
                            "updated_at": item.get("updated_at"),
                        }
                    )
            observations.append(
                Observation(
                    observation_id="github.pull_requests",
                    observed_at=now,
                    kind=FactKind.VERIFIED,
                    category="repository",
                    source="GitHub REST GET pulls",
                    summary="Observed open pull requests without comments or message bodies.",
                    value=normalized_pulls,
                )
            )
        if runs is not None:
            item = self._mapping(runs, "Actions runs")
            workflow_runs = item.get("workflow_runs", [])
            normalized_runs: list[JsonValue] = []
            if isinstance(workflow_runs, list):
                for run in workflow_runs:
                    if isinstance(run, dict):
                        normalized_runs.append(
                            {
                                "name": run.get("name"),
                                "head_sha": run.get("head_sha"),
                                "status": run.get("status"),
                                "conclusion": run.get("conclusion"),
                                "event": run.get("event"),
                            }
                        )
            observations.append(
                Observation(
                    observation_id="github.ci_status",
                    observed_at=now,
                    kind=FactKind.VERIFIED,
                    category="ci",
                    source="GitHub REST GET Actions runs",
                    summary="Observed recent default-branch workflow conclusions.",
                    value=normalized_runs,
                )
            )

        security_value: dict[str, JsonValue] = {}
        for key, value in (
            ("code_scanning", code_alerts),
            ("secret_scanning", secret_alerts),
            ("dependabot", dependabot_alerts),
        ):
            if isinstance(value, APIUnavailable):
                security_value[key] = {"available": False, "status_code": value.status_code}
            elif isinstance(value, list):
                security_value[key] = {"available": True, "open_alert_count": len(value)}
            elif value is None:
                security_value[key] = {"available": False, "status_code": None}
        observations.append(
            Observation(
                observation_id="github.security_status",
                observed_at=now,
                kind=FactKind.VERIFIED,
                category="security",
                source="GitHub REST GET security alert endpoints",
                summary="Observed alert counts or endpoint availability without alert contents.",
                value=security_value,
            )
        )
        if releases is not None:
            normalized_releases: list[JsonValue] = []
            for item in self._items(releases, "releases"):
                if isinstance(item, dict):
                    assets = item.get("assets", [])
                    downloads = 0
                    if isinstance(assets, list):
                        downloads = sum(
                            int(asset.get("download_count", 0))
                            for asset in assets
                            if isinstance(asset, dict)
                            and isinstance(asset.get("download_count", 0), int)
                        )
                    normalized_releases.append(
                        {
                            "tag": item.get("tag_name"),
                            "draft": item.get("draft"),
                            "prerelease": item.get("prerelease"),
                            "published_at": item.get("published_at"),
                            "asset_downloads": downloads,
                        }
                    )
            observations.append(
                Observation(
                    observation_id="github.release_state",
                    observed_at=now,
                    kind=FactKind.VERIFIED,
                    category="release",
                    source="GitHub REST GET releases",
                    summary="Observed release metadata and aggregate asset downloads.",
                    value=normalized_releases,
                )
            )

        critical_prefixes = ("repository:", "branches:", "pull_requests:", "ci:", "releases:")
        complete = not any(error.startswith(critical_prefixes) for error in errors)
        return ObservationReport(
            observations=observations,
            complete=complete,
            errors=errors,
            api_requests=self.request_count,
        )
