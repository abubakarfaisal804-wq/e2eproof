from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from demo.server import serve


@pytest.fixture(scope="session", autouse=True)
def browser_path() -> None:
    if Path("/usr/bin/chromium").exists():
        os.environ.setdefault("E2EPROOF_BROWSER_PATH", "/usr/bin/chromium")


@pytest.fixture()
def demo_server() -> Iterator[str]:
    server = serve("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
