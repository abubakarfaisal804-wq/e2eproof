from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .errors import EvidenceVerificationError
from .utils import Redactor, canonical_json, safe_join, sha256_bytes, sha256_file, utc_iso


@dataclass(frozen=True)
class VerificationSummary:
    valid: bool
    bundle: str
    files_checked: int
    signature_present: bool
    signature_valid: bool | None
    trusted_key_match: bool | None
    event_chain_valid: bool
    errors: list[str]
    warnings: list[str]


class EvidenceBundle:
    def __init__(self, root: Path, redactor: Redactor) -> None:
        self.root = root
        self.redactor = redactor
        self.root.mkdir(parents=True, exist_ok=False)
        self.events_path = self.root / "events.jsonl"
        self._event_index = 0
        self._last_event_hash = "0" * 64

    def path(self, relative: str | Path) -> Path:
        path = safe_join(self.root, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root.resolve()).as_posix()

    def write_text(self, relative: str | Path, text: str, *, redact: bool = True) -> str:
        output = self.path(relative)
        output.write_text(self.redactor.text(text) if redact else text, encoding="utf-8")
        return self.relative(output)

    def write_json(self, relative: str | Path, value: Any, *, redact: bool = True) -> str:
        output_value = self.redactor.value(value) if redact else value
        return self.write_text(
            relative,
            json.dumps(output_value, ensure_ascii=False, indent=2, sort_keys=True),
            redact=False,
        )

    def write_bytes(self, relative: str | Path, data: bytes) -> str:
        output = self.path(relative)
        output.write_bytes(data)
        return self.relative(output)

    def event(self, event_type: str, data: dict[str, Any]) -> str:
        base = {
            "index": self._event_index,
            "timestamp": utc_iso(),
            "type": event_type,
            "data": self.redactor.value(data),
            "prev_hash": self._last_event_hash,
        }
        event_hash = sha256_bytes(canonical_json(base))
        event = {**base, "hash": event_hash}
        with self.events_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        self._event_index += 1
        self._last_event_hash = event_hash
        return event_hash

    def finalize(self, sign_key: Path | None = None) -> dict[str, Any]:
        entries: list[dict[str, Any]] = []
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            relative = self.relative(path)
            if relative in {"manifest.json", "signature.json"}:
                continue
            entries.append(
                {
                    "path": relative,
                    "sha256": sha256_file(path),
                    "bytes": path.stat().st_size,
                }
            )

        manifest = {
            "schema_version": 1,
            "created_at": utc_iso(),
            "hash_algorithm": "sha256",
            "event_chain_head": self._last_event_hash,
            "files": entries,
        }
        manifest_bytes = canonical_json(manifest)
        self.write_json("manifest.json", manifest, redact=False)

        signature_info: dict[str, Any] | None = None
        if sign_key is not None:
            private_key = load_private_key(sign_key)
            signature = private_key.sign(manifest_bytes)
            public_key = private_key.public_key()
            public_raw = public_key.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
            signature_info = {
                "schema_version": 1,
                "algorithm": "ed25519",
                "manifest_sha256": sha256_bytes(manifest_bytes),
                "public_key_base64": base64.b64encode(public_raw).decode("ascii"),
                "signature_base64": base64.b64encode(signature).decode("ascii"),
            }
            self.write_json("signature.json", signature_info, redact=False)

        return {
            "manifest": "manifest.json",
            "manifest_sha256": sha256_bytes(manifest_bytes),
            "signed": signature_info is not None,
            "signature": "signature.json" if signature_info else None,
            "event_chain_head": self._last_event_hash,
            "file_count": len(entries),
        }


def generate_keypair(directory: Path, *, force: bool = False) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    private_path = directory / "e2eproof-private.pem"
    public_path = directory / "e2eproof-public.pem"
    if not force and (private_path.exists() or public_path.exists()):
        raise FileExistsError(f"Key files already exist in {directory}")

    private_key = Ed25519PrivateKey.generate()
    private_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    try:
        private_path.chmod(0o600)
    except OSError:
        pass
    return private_path, public_path


def load_private_key(path: Path) -> Ed25519PrivateKey:
    try:
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    except (OSError, ValueError, TypeError) as error:
        raise EvidenceVerificationError(f"Could not load private signing key: {error}") from error
    if not isinstance(key, Ed25519PrivateKey):
        raise EvidenceVerificationError("Signing key must be an Ed25519 private key")
    return key


def verify_event_chain(path: Path) -> tuple[bool, str, list[str]]:
    errors: list[str] = []
    previous = "0" * 64
    last = previous
    if not path.exists():
        return False, last, ["events.jsonl is missing"]

    with path.open("r", encoding="utf-8") as handle:
        for expected_index, line in enumerate(handle):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                errors.append(f"Invalid JSON at event line {expected_index + 1}: {error}")
                break
            claimed_hash = event.pop("hash", None)
            if event.get("index") != expected_index:
                errors.append(f"Event index mismatch at line {expected_index + 1}")
            if event.get("prev_hash") != previous:
                errors.append(f"Event previous hash mismatch at line {expected_index + 1}")
            calculated = sha256_bytes(canonical_json(event))
            if claimed_hash != calculated:
                errors.append(f"Event hash mismatch at line {expected_index + 1}")
            previous = claimed_hash or calculated
            last = previous
    return not errors, last, errors


def verify_bundle(bundle_dir: Path, trusted_public_key: Path | None = None) -> VerificationSummary:
    errors: list[str] = []
    warnings: list[str] = []
    manifest_path = bundle_dir / "manifest.json"
    if not manifest_path.exists():
        raise EvidenceVerificationError(f"manifest.json is missing in {bundle_dir}")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EvidenceVerificationError(f"Invalid manifest.json: {error}") from error

    expected_paths: set[str] = set()
    files_checked = 0
    for entry in manifest.get("files", []):
        relative = entry.get("path")
        if not isinstance(relative, str):
            errors.append("Manifest contains an invalid file path")
            continue
        expected_paths.add(relative)
        try:
            file_path = safe_join(bundle_dir, relative)
        except Exception as error:  # defensive validation of untrusted bundles
            errors.append(str(error))
            continue
        if not file_path.exists() or not file_path.is_file():
            errors.append(f"Missing artifact: {relative}")
            continue
        files_checked += 1
        actual_hash = sha256_file(file_path)
        if actual_hash != entry.get("sha256"):
            errors.append(f"Hash mismatch: {relative}")
        if file_path.stat().st_size != entry.get("bytes"):
            errors.append(f"Size mismatch: {relative}")

    actual_paths = {
        path.resolve().relative_to(bundle_dir.resolve()).as_posix()
        for path in bundle_dir.rglob("*")
        if path.is_file() and path.name not in {"manifest.json", "signature.json"}
    }
    extra = sorted(actual_paths - expected_paths)
    if extra:
        warnings.append("Unlisted files are present: " + ", ".join(extra))

    chain_valid, chain_head, chain_errors = verify_event_chain(bundle_dir / "events.jsonl")
    errors.extend(chain_errors)
    if chain_head != manifest.get("event_chain_head"):
        errors.append("Event chain head does not match manifest")
        chain_valid = False

    signature_path = bundle_dir / "signature.json"
    signature_present = signature_path.exists()
    signature_valid: bool | None = None
    trusted_key_match: bool | None = None
    if trusted_public_key is not None and not signature_present:
        errors.append("A trusted public key was supplied but the bundle is not signed")
        trusted_key_match = False
    if signature_present:
        try:
            signature_info = json.loads(signature_path.read_text(encoding="utf-8"))
            manifest_bytes = canonical_json(manifest)
            if sha256_bytes(manifest_bytes) != signature_info.get("manifest_sha256"):
                raise EvidenceVerificationError("Signed manifest hash does not match")
            embedded_public_raw = base64.b64decode(
                signature_info["public_key_base64"], validate=True
            )
            public_key = Ed25519PublicKey.from_public_bytes(embedded_public_raw)
            if trusted_public_key is not None:
                trusted = serialization.load_pem_public_key(trusted_public_key.read_bytes())
                if not isinstance(trusted, Ed25519PublicKey):
                    raise EvidenceVerificationError("Trusted public key must be Ed25519")
                trusted_raw = trusted.public_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PublicFormat.Raw,
                )
                trusted_key_match = trusted_raw == embedded_public_raw
                if not trusted_key_match:
                    raise EvidenceVerificationError(
                        "Embedded signer does not match trusted public key"
                    )
            public_key.verify(
                base64.b64decode(signature_info["signature_base64"], validate=True),
                manifest_bytes,
            )
            signature_valid = True
            if trusted_public_key is None:
                warnings.append(
                    "Signature is cryptographically valid, but signer identity was not checked "
                    "against a trusted public key."
                )
        except (
            OSError,
            KeyError,
            ValueError,
            TypeError,
            json.JSONDecodeError,
            InvalidSignature,
            EvidenceVerificationError,
        ) as error:
            signature_valid = False
            errors.append(f"Invalid signature: {error}")

    return VerificationSummary(
        valid=not errors,
        bundle=str(bundle_dir),
        files_checked=files_checked,
        signature_present=signature_present,
        signature_valid=signature_valid,
        trusted_key_match=trusted_key_match,
        event_chain_valid=chain_valid,
        errors=errors,
        warnings=warnings,
    )
