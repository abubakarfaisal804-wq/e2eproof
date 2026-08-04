from __future__ import annotations

import json
from pathlib import Path

from e2eproof.cli import main


def test_cli_init_validate_schema_doctor(tmp_path: Path, capsys) -> None:
    contract = tmp_path / "contract.yaml"
    assert main(["init", str(contract)]) == 0
    assert main(["validate", str(contract)]) == 0
    schema = tmp_path / "schema.json"
    assert main(["schema", "--output", str(schema)]) == 0
    assert '"Contract"' in schema.read_text()
    code = main(["doctor", "--contract", str(contract), "--json"])
    assert code in {0, 2}
    output = capsys.readouterr().out
    assert "checks" in output


def test_cli_run_verify_keygen_and_errors(tmp_path: Path, demo_server: str, capsys) -> None:
    import yaml

    contract_path = tmp_path / "http.yaml"
    contract_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "name": "CLI HTTP verification",
                "base_url": demo_server,
                "policy": {"allowed_hosts": ["127.0.0.1", "localhost"]},
                "evidence": {
                    "output_dir": str(tmp_path / "evidence"),
                    "trace": "never",
                    "screenshot": "never",
                },
                "flows": [
                    {
                        "id": "health",
                        "claim": "The demo health endpoint responds successfully.",
                        "steps": [
                            {
                                "type": "http.request",
                                "url": "/health",
                                "assertions": {"status": 200},
                            }
                        ],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    keys = tmp_path / "keys"
    assert main(["keygen", str(keys)]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "run",
                str(contract_path),
                "--run-id",
                "cli",
                "--sign-key",
                str(keys / "e2eproof-private.pem"),
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    bundle = tmp_path / "evidence" / "cli"
    assert (
        main(
            [
                "verify",
                str(bundle),
                "--public-key",
                str(keys / "e2eproof-public.pem"),
                "--json",
            ]
        )
        == 0
    )
    verification = json.loads(capsys.readouterr().out)
    assert verification["trusted_key_match"] is True
    assert main(["validate", str(tmp_path / "missing.yaml")]) == 2
    assert "ERROR" in capsys.readouterr().err


def test_cli_remaining_branches(tmp_path: Path, monkeypatch, capsys) -> None:
    from types import SimpleNamespace

    import yaml

    import e2eproof.cli as cli
    from e2eproof.models import Contract

    contract_path = tmp_path / "c.yaml"
    contract_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "name": "CLI branch contract",
                "base_url": "https://example.com",
                "secrets": {"token": {"env": "CLI_MISSING_SECRET", "required": True}},
                "flows": [
                    {
                        "id": "x",
                        "claim": "The health endpoint works as expected.",
                        "steps": [{"type": "http.request", "url": "/health"}],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("CLI_MISSING_SECRET", raising=False)
    assert main(["doctor", "--contract", str(contract_path)]) == 2
    assert "required-secrets" in capsys.readouterr().out
    assert main(["doctor", "--contract", str(tmp_path / "missing.yaml")]) == 2

    fake_bundle = tmp_path / "fake-bundle"
    fake_bundle.mkdir()
    fake_result = SimpleNamespace(status="passed", contract_name="Fake", summary={"passed": 1})
    monkeypatch.setattr(cli, "run_contract", lambda *a, **k: (fake_result, fake_bundle))
    assert (
        main(
            [
                "run",
                str(contract_path),
                "--headed",
                "--browser",
                "firefox",
                "--browser-path",
                "/browser/firefox",
                "--sign-key",
                "key.pem",
            ]
        )
        == 0
    )
    assert "Report:" in capsys.readouterr().out

    generated = Contract.model_validate(
        {
            "version": 1,
            "name": "Generated CLI contract",
            "base_url": "https://example.com",
            "flows": [
                {
                    "id": "x",
                    "claim": "The endpoint provides a valid health result.",
                    "steps": [{"type": "http.request", "url": "/health"}],
                }
            ],
        }
    )
    monkeypatch.setattr(cli, "draft_contract", lambda **kwargs: generated)
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("independent read-back", encoding="utf-8")
    generated_path = tmp_path / "generated.yaml"
    assert (
        main(
            [
                "ai-draft",
                "--base-url",
                "https://example.com",
                "--claim",
                "health",
                "--requirements-file",
                str(requirements),
                "--output",
                str(generated_path),
            ]
        )
        == 0
    )
    assert generated_path.exists()

    monkeypatch.setattr(cli, "diagnose_result", lambda *a, **k: "# Diagnosis")
    result = tmp_path / "result.json"
    result.write_text("{}")
    diagnosis = tmp_path / "diagnosis.md"
    assert main(["ai-diagnose", str(result), "--output", str(diagnosis)]) == 0
    assert diagnosis.read_text() == "# Diagnosis"
    assert main(["ai-diagnose", str(result)]) == 0
    assert "Diagnosis" in capsys.readouterr().out
    assert main(["schema"]) == 0
    assert '"title": "Contract"' in capsys.readouterr().out


def test_browser_doctor_detects_system_browser(monkeypatch) -> None:
    import e2eproof.cli as cli

    monkeypatch.setattr(cli, "find_browser_executable", lambda engine: "/browser/chrome")
    assert cli._browser_doctor_detail() == (True, "/browser/chrome")


def test_browser_doctor_detects_playwright_managed_browser(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace

    import e2eproof.cli as cli

    executable = tmp_path / "chromium"
    executable.write_text("browser", encoding="utf-8")

    class FakePlaywrightContext:
        def __enter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(executable_path=str(executable)))

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(cli, "find_browser_executable", lambda engine: None)
    monkeypatch.setattr(cli, "sync_playwright", lambda: FakePlaywrightContext())
    assert cli._browser_doctor_detail() == (True, str(executable))


def test_cli_install_browser_demo_and_quickstart(monkeypatch, tmp_path: Path) -> None:
    import e2eproof.cli as cli

    installed: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        cli,
        "_install_browser",
        lambda engine, with_deps=False: installed.append((engine, with_deps)),
    )
    assert main(["install-browser", "firefox", "--with-deps"]) == 0
    assert installed == [("firefox", True)]

    runs: list[dict[str, object]] = []
    monkeypatch.setattr(cli, "_run_demo", lambda **kwargs: runs.append(kwargs) or 0)
    assert (
        main(["demo", "--browser", "webkit", "--output", str(tmp_path), "--no-open", "--json"]) == 0
    )
    assert runs[-1]["engine"] == "webkit"
    assert runs[-1]["no_open"] is True

    monkeypatch.setattr(cli, "_browser_doctor_detail", lambda engine="chromium": (False, "missing"))
    assert main(["quickstart", "--browser", "chromium", "--yes", "--no-open"]) == 0
    assert installed[-1] == ("chromium", False)
    assert runs[-1]["engine"] == "chromium"


def test_doctor_supports_selected_browser(monkeypatch) -> None:
    import e2eproof.cli as cli

    monkeypatch.setattr(
        cli, "_browser_doctor_detail", lambda engine="chromium": (True, f"/{engine}")
    )
    payload = cli._doctor(None, "webkit")
    assert payload["ok"] is True
    assert payload["browser"] == "webkit"
    assert any(item["name"] == "webkit-browser" for item in payload["checks"])
