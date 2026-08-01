from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from e2eproof.config import load_contract
from e2eproof.evidence import verify_bundle
from e2eproof.runner import run_contract


def _write_contract(path: Path, base_url: str, expected_count: int = 1) -> None:
    data = {
        "version": 1,
        "name": "HTTP exact-once runner",
        "base_url": base_url,
        "variables": {"email": "http+{{run_id}}@example.com"},
        "policy": {"allowed_hosts": ["127.0.0.1", "localhost"], "timeout_ms": 3000},
        "evidence": {
            "output_dir": str(path.parent / "evidence"),
            "screenshot": "never",
            "trace": "never",
            "include_network": True,
        },
        "flows": [
            {
                "id": "http-exact-once",
                "claim": "One API write creates exactly one readable lead.",
                "steps": [
                    {
                        "type": "http.request",
                        "method": "POST",
                        "url": "/api/reset",
                        "json_body": {},
                        "assertions": {"status": 200},
                    },
                    {
                        "type": "http.request",
                        "method": "POST",
                        "url": "/api/leads",
                        "json_body": {"email": "{{email}}"},
                        "assertions": {
                            "status": 201,
                            "json": [{"path": "$.email", "equals": "{{email}}"}],
                        },
                    },
                    {
                        "type": "http.poll",
                        "method": "GET",
                        "url": "/api/leads?email={{email}}",
                        "poll_timeout_ms": 1000,
                        "interval_ms": 50,
                        "assertions": {
                            "status": 200,
                            "json": [{"path": "$.count", "equals": expected_count}],
                        },
                    },
                ],
            }
        ],
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_http_only_runner_passes_and_bundle_verifies(tmp_path: Path, demo_server: str) -> None:
    contract_path = tmp_path / "pass.yaml"
    _write_contract(contract_path, demo_server)
    result, bundle = run_contract(
        load_contract(contract_path), contract_path=contract_path, run_id="pass"
    )
    assert result.status == "passed"
    assert result.summary["passed"] == 1
    assert (bundle / "report.html").exists()
    assert (bundle / "junit.xml").exists()
    assert verify_bundle(bundle).valid
    payload = json.loads((bundle / "result.json").read_text())
    assert payload["status"] == "passed"


def test_http_only_runner_fails_on_wrong_side_effect(tmp_path: Path, demo_server: str) -> None:
    contract_path = tmp_path / "fail.yaml"
    _write_contract(contract_path, demo_server, expected_count=2)
    result, bundle = run_contract(
        load_contract(contract_path), contract_path=contract_path, run_id="fail"
    )
    assert result.status == "failed"
    assert "timed out" in result.flows[0].attempts[0].failure.lower()
    assert verify_bundle(bundle).valid


def test_runner_retry_flaky_and_signed_trace(tmp_path: Path, demo_server: str) -> None:
    from e2eproof.evidence import generate_keypair

    private_key, _ = generate_keypair(tmp_path / "keys")
    contract_path = tmp_path / "flaky.yaml"
    data = {
        "version": 1,
        "name": "Flaky signed verification",
        "base_url": demo_server,
        "variables": {"email": "flaky+{{run_id}}@example.com"},
        "policy": {
            "allowed_hosts": ["127.0.0.1", "localhost"],
            "retries": 1,
            "fail_on_flaky": True,
        },
        "evidence": {
            "output_dir": str(tmp_path / "evidence"),
            "screenshot": "failure",
            "trace": "always",
            "include_console": True,
            "include_network": True,
            "include_page_html": True,
            "sign_key": str(private_key),
        },
        "flows": [
            {
                "id": "flaky",
                "claim": "A temporary backend failure is detected and classified as flaky.",
                "steps": [
                    {
                        "type": "http.request",
                        "method": "POST",
                        "url": "/api/flaky",
                        "json_body": {"email": "{{email}}"},
                        "assertions": {"status": 201},
                    },
                ],
            }
        ],
    }
    contract_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    result, bundle = run_contract(
        load_contract(contract_path), contract_path=contract_path, run_id="flaky"
    )
    assert result.status == "failed"  # fail_on_flaky converts the run to failure
    assert result.flows[0].status == "flaky"
    assert len(result.flows[0].attempts) == 2
    verified = verify_bundle(bundle)
    assert verified.valid and verified.signature_valid is True
    assert (bundle / "flows" / "flaky" / "attempt-1" / "trace.zip").exists()
    assert (bundle / "flows" / "flaky" / "attempt-1" / "step-001-failure.png").exists()


def test_secret_binary_artifacts_fail_closed(tmp_path: Path, monkeypatch) -> None:
    from e2eproof.errors import ContractError

    monkeypatch.setenv("E2EPROOF_TEST_SECRET", "secret-value")
    contract_path = tmp_path / "secret.yaml"
    data = {
        "version": 1,
        "name": "Secret safety contract",
        "base_url": "https://example.com",
        "secrets": {"token": {"env": "E2EPROOF_TEST_SECRET"}},
        "evidence": {"screenshot": "failure", "trace": "failure"},
        "flows": [
            {
                "id": "x",
                "claim": "Secrets are protected from binary artifacts.",
                "steps": [{"type": "set.variable", "variable": "x", "value": "ok"}],
            }
        ],
    }
    contract_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(ContractError, match="Binary screenshots"):
        run_contract(load_contract(contract_path), contract_path=contract_path, run_id="secret")
