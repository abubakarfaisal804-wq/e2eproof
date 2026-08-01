from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from e2eproof.config import load_contract, write_sample_contract
from e2eproof.errors import ContractError
from e2eproof.models import Contract, LocatorSpec


def minimal_contract() -> dict:
    return {
        "version": 1,
        "name": "Minimal valid contract",
        "base_url": "https://example.com",
        "flows": [
            {
                "id": "health",
                "claim": "The API health endpoint responds successfully.",
                "steps": [
                    {
                        "type": "http.request",
                        "url": "/health",
                        "assertions": {"status": 200},
                    }
                ],
            }
        ],
    }


def test_contract_validates_strictly() -> None:
    contract = Contract.model_validate(minimal_contract())
    assert contract.flows[0].id == "health"
    data = minimal_contract()
    data["unexpected"] = True
    with pytest.raises(ValidationError, match="Extra inputs"):
        Contract.model_validate(data)


def test_duplicate_flow_ids_rejected() -> None:
    data = minimal_contract()
    data["flows"].append(data["flows"][0].copy())
    with pytest.raises(ValidationError, match="unique"):
        Contract.model_validate(data)


def test_locator_exactly_one_strategy() -> None:
    assert LocatorSpec(label="Email").label == "Email"
    with pytest.raises(ValidationError, match="exactly one"):
        LocatorSpec(label="Email", css="#email")
    with pytest.raises(ValidationError, match="name can only"):
        LocatorSpec(label="Email", name="x")


def test_load_and_sample_contract(tmp_path: Path) -> None:
    sample = write_sample_contract(tmp_path / "e2eproof.yaml")
    assert load_contract(sample).name.startswith("Lead form")
    with pytest.raises(ContractError, match="overwrite"):
        write_sample_contract(sample)
    bad = tmp_path / "bad.yaml"
    bad.write_text("flows: [", encoding="utf-8")
    with pytest.raises(ContractError, match="Could not read YAML"):
        load_contract(bad)
    root = tmp_path / "root.yaml"
    root.write_text("- not-a-map", encoding="utf-8")
    with pytest.raises(ContractError, match="root"):
        load_contract(root)


def test_literal_secret_rejected(tmp_path: Path) -> None:
    secret = tmp_path / "secret.yaml"
    secret.write_text(
        "version: 1\nname: Literal secret bad\nbase_url: https://example.com\n"
        "variables:\n  token: sk-proj-abcdefghijklmnop123456\n"
        "flows:\n  - id: x\n    claim: The endpoint should work safely.\n"
        "    steps:\n      - {type: http.request, url: /health}\n",
        encoding="utf-8",
    )
    with pytest.raises(ContractError, match="literal credential"):
        load_contract(secret)
