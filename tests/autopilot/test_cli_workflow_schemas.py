from __future__ import annotations

import json
from pathlib import Path

import yaml

from e2eproof.autopilot.schema_export import write_json_schemas
from e2eproof.cli import main

ROOT = Path(__file__).resolve().parents[2]


def test_cli_dry_run_writes_json_brief_summary_and_replays(tmp_path: Path, capsys) -> None:
    arguments = [
        "autopilot",
        "dry-run",
        "--input",
        str(ROOT / "evals" / "autopilot" / "fixtures" / "local-cycle.json"),
        "--repository-root",
        str(ROOT),
        "--seed-dir",
        str(ROOT / "ops"),
        "--state-dir",
        str(tmp_path / "state"),
        "--cycle-id",
        "cli-test-cycle",
        "--output",
        str(tmp_path / "result.json"),
        "--brief",
        str(tmp_path / "brief.json"),
        "--summary",
        str(tmp_path / "summary.md"),
    ]
    assert main(arguments) == 0
    assert "AUTOPILOT SELECTED" in capsys.readouterr().out
    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert result["selected_task_id"] == "enable-dependabot-alerts"
    assert json.loads((tmp_path / "brief.json").read_text(encoding="utf-8"))["dry_run"]
    assert "Model calls: `0`" in (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert main([*arguments, "--json"]) == 0
    assert '"cycle_id": "cli-test-cycle"' in capsys.readouterr().out


def test_cli_schema_export_and_committed_schemas_are_reproducible(tmp_path: Path, capsys) -> None:
    generated = tmp_path / "schemas"
    assert main(["autopilot", "schemas", "--output-dir", str(generated)]) == 0
    assert "autopilot-input.schema.json" in capsys.readouterr().out
    for path in write_json_schemas(tmp_path / "second"):
        committed = ROOT / "docs" / "schemas" / path.name
        assert json.loads(committed.read_text(encoding="utf-8")) == json.loads(
            path.read_text(encoding="utf-8")
        )


def test_workflow_is_hourly_dispatchable_read_only_and_artifact_only() -> None:
    path = ROOT / ".github" / "workflows" / "autopilot.yml"
    text = path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    triggers = workflow.get("on", workflow.get(True))
    assert triggers["schedule"] == [{"cron": "23 * * * *"}]
    assert "workflow_dispatch" in triggers
    assert set(workflow["permissions"].values()) == {"read"}
    job = workflow["jobs"]["dry-run"]
    assert job["timeout-minutes"] == 15
    assert job["runs-on"] == "ubuntu-latest"
    assert "persist-credentials: false" in text
    assert "--github-live" in text
    assert "actions/upload-artifact@v7" in text
    for prohibited in (
        "git push",
        "gh pr create",
        "gh pr merge",
        "gh release",
        "pull_request_target",
        "contents: write",
        "id-token: write",
    ):
        assert prohibited not in text


def test_checked_in_state_covers_every_required_ledger() -> None:
    required = {
        "state.json",
        "backlog.json",
        "metrics.json",
        "approvals.json",
        "risks.json",
        "observations.jsonl",
        "decisions.jsonl",
        "experiments.jsonl",
        "outcomes.jsonl",
    }
    assert required <= {path.name for path in (ROOT / "ops").iterdir()}
    for name in ("state.json", "backlog.json", "metrics.json", "approvals.json", "risks.json"):
        assert json.loads((ROOT / "ops" / name).read_text(encoding="utf-8"))["schema_version"] == 1
