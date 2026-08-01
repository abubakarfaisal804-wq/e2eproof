from __future__ import annotations

import json
from pathlib import Path

import pytest

from e2eproof.evidence import EvidenceBundle, generate_keypair, verify_bundle
from e2eproof.utils import Redactor


def test_signed_bundle_and_tamper_detection(tmp_path: Path) -> None:
    private_key, public_key = generate_keypair(tmp_path / "keys")
    assert private_key.exists() and public_key.exists()
    bundle = EvidenceBundle(tmp_path / "bundle", Redactor(["secret-value"]))
    bundle.event("run.started", {"token": "secret-value"})
    bundle.write_text("artifact.txt", "contains secret-value")
    bundle.event("run.finished", {"status": "passed"})
    info = bundle.finalize(sign_key=private_key)
    assert info["signed"] is True
    verified = verify_bundle(tmp_path / "bundle", trusted_public_key=public_key)
    assert verified.valid
    assert verified.signature_valid is True
    assert verified.trusted_key_match is True
    assert "secret-value" not in (tmp_path / "bundle" / "artifact.txt").read_text()
    assert "secret-value" not in (tmp_path / "bundle" / "events.jsonl").read_text()

    (tmp_path / "bundle" / "artifact.txt").write_text("tampered", encoding="utf-8")
    tampered = verify_bundle(tmp_path / "bundle")
    assert not tampered.valid
    assert any("Hash mismatch" in item for item in tampered.errors)


def test_event_chain_tamper(tmp_path: Path) -> None:
    bundle = EvidenceBundle(tmp_path / "bundle", Redactor([]))
    bundle.event("a", {"x": 1})
    bundle.event("b", {"x": 2})
    bundle.finalize()
    events = tmp_path / "bundle" / "events.jsonl"
    rows = events.read_text().splitlines()
    item = json.loads(rows[0])
    item["data"]["x"] = 999
    rows[0] = json.dumps(item)
    events.write_text("\n".join(rows) + "\n")
    result = verify_bundle(tmp_path / "bundle")
    assert not result.valid
    assert any("Event hash mismatch" in error for error in result.errors)


def test_bundle_missing_extra_and_bad_signature(tmp_path: Path) -> None:
    from e2eproof.errors import EvidenceVerificationError

    with pytest.raises(EvidenceVerificationError, match="manifest"):
        verify_bundle(tmp_path / "missing")

    bundle = EvidenceBundle(tmp_path / "bundle2", Redactor([]))
    bundle.write_text("a.txt", "a")
    bundle.event("done", {})
    bundle.finalize()
    (tmp_path / "bundle2" / "extra.txt").write_text("extra")
    summary = verify_bundle(tmp_path / "bundle2")
    assert summary.valid
    assert summary.warnings

    (tmp_path / "bundle2" / "signature.json").write_text("{}")
    bad = verify_bundle(tmp_path / "bundle2")
    assert not bad.valid
    assert bad.signature_valid is False


def test_evidence_validation_edge_cases(tmp_path: Path) -> None:
    from e2eproof.errors import EvidenceVerificationError
    from e2eproof.evidence import load_private_key, verify_event_chain

    bundle = EvidenceBundle(tmp_path / "bytes", Redactor([]))
    assert bundle.write_bytes("data.bin", b"abc") == "data.bin"
    bundle.event("done", {})
    bundle.finalize()
    assert verify_bundle(tmp_path / "bytes").valid

    bad_manifest = tmp_path / "bad-manifest"
    bad_manifest.mkdir()
    (bad_manifest / "manifest.json").write_text("{")
    with pytest.raises(EvidenceVerificationError, match="Invalid manifest"):
        verify_bundle(bad_manifest)

    malformed = tmp_path / "malformed-events.jsonl"
    malformed.write_text("not-json\n")
    valid, _, errors = verify_event_chain(malformed)
    assert not valid and "Invalid JSON" in errors[0]
    missing_valid, _, missing_errors = verify_event_chain(tmp_path / "missing-events")
    assert not missing_valid and missing_errors

    not_key = tmp_path / "not-key.pem"
    not_key.write_text("not a key")
    with pytest.raises(EvidenceVerificationError, match="Could not load"):
        load_private_key(not_key)

    original = tmp_path / "missing-artifact"
    b = EvidenceBundle(original, Redactor([]))
    b.write_text("gone.txt", "x")
    b.event("done", {})
    b.finalize()
    (original / "gone.txt").unlink()
    summary = verify_bundle(original)
    assert not summary.valid
    assert any("Missing artifact" in error for error in summary.errors)


def test_trusted_key_mismatch_is_rejected(tmp_path: Path) -> None:
    private_a, _ = generate_keypair(tmp_path / "a")
    _, public_b = generate_keypair(tmp_path / "b")
    bundle = EvidenceBundle(tmp_path / "signed-mismatch", Redactor([]))
    bundle.event("done", {})
    bundle.finalize(sign_key=private_a)
    result = verify_bundle(tmp_path / "signed-mismatch", trusted_public_key=public_b)
    assert not result.valid
    assert result.trusted_key_match is False
    assert any("trusted public key" in error for error in result.errors)
