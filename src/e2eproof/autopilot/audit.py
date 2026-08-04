from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from pydantic import Field, JsonValue

from .errors import AutopilotError
from .schemas import SCHEMA_VERSION, AutopilotModel, ensure_safe_payload


class AuditEvent(AutopilotModel):
    schema_version: int = SCHEMA_VERSION
    event_id: str
    cycle_id: str
    sequence: int = Field(ge=1)
    recorded_at: datetime
    event_type: str
    data: dict[str, JsonValue]
    previous_hash: str
    event_hash: str


class AuditLog:
    def __init__(self, state_root: Path) -> None:
        self.path = (state_root.resolve() / "audit.jsonl").resolve()
        if self.path.parent != state_root.resolve():
            raise AutopilotError("Audit log path escaped the state directory")

    def _events(self) -> list[AuditEvent]:
        if not self.path.exists():
            return []
        events: list[AuditEvent] = []
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                event = AuditEvent.model_validate_json(line)
                ensure_safe_payload(event.model_dump(mode="json"), "audit event")
                events.append(event)
            except ValueError as error:
                raise AutopilotError(
                    f"Invalid audit event at line {line_number}: {error}"
                ) from error
        return events

    def append(
        self,
        *,
        event_id: str,
        cycle_id: str,
        recorded_at: datetime,
        event_type: str,
        data: dict[str, JsonValue],
    ) -> AuditEvent:
        ensure_safe_payload(data, "audit.data")
        events = self._events()
        for event in events:
            if event.event_id == event_id:
                return event
        previous_hash = events[-1].event_hash if events else "0" * 64
        unsigned = {
            "schema_version": SCHEMA_VERSION,
            "event_id": event_id,
            "cycle_id": cycle_id,
            "sequence": len(events) + 1,
            "recorded_at": recorded_at.isoformat(),
            "event_type": event_type,
            "data": data,
            "previous_hash": previous_hash,
        }
        canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
        event = AuditEvent(
            event_id=event_id,
            cycle_id=cycle_id,
            sequence=len(events) + 1,
            recorded_at=recorded_at,
            event_type=event_type,
            data=data,
            previous_hash=previous_hash,
            event_hash=hashlib.sha256(canonical).hexdigest(),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            payload = (event.model_dump_json() + "\n").encode("utf-8")
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return event

    def verify(self) -> tuple[bool, str]:
        previous_hash = "0" * 64
        for event in self._events():
            unsigned = {
                "schema_version": event.schema_version,
                "event_id": event.event_id,
                "cycle_id": event.cycle_id,
                "sequence": event.sequence,
                "recorded_at": event.recorded_at.isoformat(),
                "event_type": event.event_type,
                "data": event.data,
                "previous_hash": event.previous_hash,
            }
            if unsigned["previous_hash"] != previous_hash:
                return False, f"broken previous hash at sequence {event.sequence}"
            canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
            if hashlib.sha256(canonical).hexdigest() != event.event_hash:
                return False, f"event hash mismatch at sequence {event.sequence}"
            previous_hash = event.event_hash
        return True, "ok"
