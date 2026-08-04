from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from demo.server import serve
from e2eproof.runner import find_browser_executable


@pytest.fixture(scope="session", autouse=True)
def browser_path() -> None:
    configured = os.getenv("E2EPROOF_BROWSER_PATH")
    if configured and Path(configured).is_file():
        return
    executable = find_browser_executable("chromium")
    if executable:
        os.environ["E2EPROOF_BROWSER_PATH"] = executable


@pytest.fixture()
def chromium_launch_options() -> dict[str, object]:
    options: dict[str, object] = {"headless": True}
    executable = os.getenv("E2EPROOF_BROWSER_PATH")
    if executable and Path(executable).is_file():
        options["executable_path"] = executable
    if os.name != "nt" and hasattr(os, "geteuid") and os.geteuid() == 0:
        options["args"] = ["--no-sandbox"]
    return options


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
