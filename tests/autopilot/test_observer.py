from __future__ import annotations

import json
from pathlib import Path

import httpx

from e2eproof.autopilot.observer import GitHubObserver, observe_local_repository
from e2eproof.autopilot.schemas import BudgetConfig

from .helpers import NOW

ROOT = Path(__file__).resolve().parents[2]


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    assert request.method == "GET"
    if path.endswith("/branches"):
        return httpx.Response(
            200, json=[{"name": "main", "protected": True, "commit": {"sha": "a" * 40}}]
        )
    if path.endswith("/branches/main/protection"):
        return httpx.Response(
            200,
            json={
                "required_status_checks": {"strict": True, "contexts": ["quality-gate"]},
                "allow_force_pushes": {"enabled": False},
                "allow_deletions": {"enabled": False},
            },
        )
    if path.endswith("/pulls"):
        return httpx.Response(
            200,
            json=[
                {
                    "number": 6,
                    "title": "Update actions",
                    "draft": False,
                    "head": {"ref": "deps"},
                    "updated_at": "2026-08-04T00:00:00Z",
                }
            ],
        )
    if path.endswith("/actions/runs"):
        return httpx.Response(
            200,
            json={
                "workflow_runs": [
                    {
                        "name": "quality",
                        "head_sha": "a" * 40,
                        "status": "completed",
                        "conclusion": "success",
                        "event": "push",
                    }
                ]
            },
        )
    if path.endswith("/code-scanning/alerts"):
        return httpx.Response(200, json=[])
    if path.endswith("/secret-scanning/alerts") or path.endswith("/dependabot/alerts"):
        return httpx.Response(403, json={"message": "unavailable"})
    if path.endswith("/releases"):
        return httpx.Response(
            200,
            json=[
                {
                    "tag_name": "v0.2.0",
                    "draft": False,
                    "prerelease": True,
                    "published_at": "2026-08-02T00:00:00Z",
                    "assets": [{"download_count": 0}],
                }
            ],
        )
    return httpx.Response(
        200,
        json={
            "full_name": "owner/repo",
            "visibility": "public",
            "archived": False,
            "default_branch": "main",
        },
    )


def test_local_observer_records_head_and_manifest_hashes() -> None:
    observations = observe_local_repository(ROOT, now=NOW, process_timeout_seconds=5)
    by_id = {item.observation_id: item for item in observations}
    assert len(by_id["local.repository"].value["head"]) == 40
    assert by_id["local.dependency_state"].value["project_version"] == "0.2.0"
    assert by_id["local.repository"].kind.value == "verified"


def test_github_observer_is_get_only_bounded_and_data_minimized() -> None:
    observer = GitHubObserver(
        repository="owner/repo",
        token="test-token-not-persisted",
        budgets=BudgetConfig(api_request_limit=9, api_retries=0),
        transport=httpx.MockTransport(_handler),
    )
    report = observer.observe(now=NOW)
    assert report.complete
    assert report.errors == []
    assert report.api_requests == 9
    by_id = {item.observation_id: item for item in report.observations}
    assert by_id["github.pull_requests"].value[0]["number"] == 6
    assert by_id["github.branches"].value["main_protection"]["force_pushes_allowed"] is False
    assert by_id["github.security_status"].value["dependabot"]["available"] is False
    assert by_id["github.release_state"].value[0]["asset_downloads"] == 0
    assert "test-token-not-persisted" not in json.dumps(
        [item.model_dump(mode="json") for item in report.observations]
    )


def test_github_observer_retries_transient_failure_within_budget() -> None:
    attempts = 0

    def flaky(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        if request.url.path == "/repos/owner/repo" and attempts == 0:
            attempts += 1
            return httpx.Response(500, json={"message": "temporary"})
        return _handler(request)

    observer = GitHubObserver(
        repository="owner/repo",
        token="token",
        budgets=BudgetConfig(api_request_limit=10, api_retries=1),
        transport=httpx.MockTransport(flaky),
        sleeper=lambda _: None,
    )
    report = observer.observe(now=NOW)
    assert report.complete
    assert report.api_requests == 10


def test_github_observer_fails_closed_on_critical_error_and_budget_exhaustion() -> None:
    def broken_actions(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/actions/runs"):
            return httpx.Response(500, json={"message": "down"})
        return _handler(request)

    observer = GitHubObserver(
        repository="owner/repo",
        token="token",
        budgets=BudgetConfig(api_request_limit=9, api_retries=0),
        transport=httpx.MockTransport(broken_actions),
    )
    report = observer.observe(now=NOW)
    assert not report.complete
    assert any(item.startswith("ci:") for item in report.errors)

    exhausted = GitHubObserver(
        repository="owner/repo",
        token="token",
        budgets=BudgetConfig(api_request_limit=1, api_retries=0),
        transport=httpx.MockTransport(_handler),
    ).observe(now=NOW)
    assert not exhausted.complete
    assert exhausted.api_requests == 1
    assert any("budget exhausted" in item for item in exhausted.errors)
