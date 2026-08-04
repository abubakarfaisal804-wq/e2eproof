from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import suppress
from pathlib import Path
from types import TracebackType

from .errors import AutopilotError


class ProcessLock:
    """Cross-platform, bounded, stale-recovering lock for one state directory."""

    def __init__(
        self,
        path: Path,
        *,
        timeout_seconds: float,
        stale_after_seconds: int,
        poll_seconds: float = 0.05,
    ) -> None:
        self.path = path.resolve()
        self.timeout_seconds = timeout_seconds
        self.stale_after_seconds = stale_after_seconds
        self.poll_seconds = poll_seconds
        self.token = uuid.uuid4().hex
        self.recovered_stale_lock = False
        self._acquired = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout_seconds
        payload = json.dumps(
            {"pid": os.getpid(), "token": self.token, "acquired_unix": time.time()},
            sort_keys=True,
        ).encode("utf-8")
        while True:
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                try:
                    age = time.time() - self.path.stat().st_mtime
                except FileNotFoundError:
                    continue
                if age > self.stale_after_seconds:
                    try:
                        self.path.unlink()
                        self.recovered_stale_lock = True
                    except FileNotFoundError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    raise AutopilotError(
                        f"Autopilot state is locked by another process: {self.path}"
                    ) from None
                time.sleep(self.poll_seconds)
                continue
            try:
                os.write(descriptor, payload)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            self._acquired = True
            return

    def release(self) -> None:
        if not self._acquired:
            return
        try:
            current = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            current = {}
        if current.get("token") == self.token:
            with suppress(FileNotFoundError):
                self.path.unlink()
        self._acquired = False

    def __enter__(self) -> ProcessLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()
