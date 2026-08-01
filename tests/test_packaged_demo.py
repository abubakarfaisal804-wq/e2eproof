from __future__ import annotations

import json
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from e2eproof.cli import _run_demo
from e2eproof.demo_server import serve


def _read(url: str) -> tuple[int, bytes]:
    try:
        with urlopen(url, timeout=3) as response:  # noqa: S310 - fixed local test server
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()


def _post(url: str, payload: bytes, content_type: str = "application/json") -> tuple[int, bytes]:
    request = Request(  # noqa: S310 - fixed local test server
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": content_type},
    )
    try:
        with urlopen(request, timeout=3) as response:  # noqa: S310 - fixed local test server
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()


def test_packaged_demo_server_endpoints() -> None:
    server = serve("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base = f"http://{host}:{port}"
    try:
        status, body = _read(base + "/health")
        assert status == 200
        assert json.loads(body) == {"ok": True}

        status, body = _read(base + "/app/real")
        assert status == 200
        assert b"Submit lead" in body

        status, _ = _post(base + "/api/leads", b"not-json")
        assert status == 400
        status, _ = _post(base + "/api/leads", b'{"email":"bad"}')
        assert status == 422

        status, body = _post(base + "/api/leads", b'{"email":"a@example.com"}')
        assert status == 201
        assert json.loads(body)["email"] == "a@example.com"

        status, body = _read(base + "/api/leads?email=a%40example.com")
        assert status == 200
        assert json.loads(body)["count"] == 1

        status, body = _read(base + "/api/provider")
        assert status == 503
        assert json.loads(body)["provider"] == "mock"

        status, _ = _post(base + "/api/flaky", b'{"email":"f@example.com"}')
        assert status == 503
        status, _ = _post(base + "/api/flaky", b'{"email":"f@example.com"}')
        assert status == 201

        status, _ = _post(base + "/api/reset", b"{}")
        assert status == 200
        status, body = _read(base + "/api/leads")
        assert json.loads(body)["count"] == 0

        status, _ = _read(base + "/missing")
        assert status == 404
        status, _ = _post(base + "/missing", b"{}")
        assert status == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.browser
def test_packaged_real_browser_demo(tmp_path: Path) -> None:
    code = _run_demo(
        engine="chromium",
        headed=False,
        output=tmp_path / "evidence",
        no_open=True,
        json_output=True,
    )
    reports = list((tmp_path / "evidence").glob("*/report.html"))
    assert reports
    if code != 0:
        result_files = list((tmp_path / "evidence").glob("*/result.json"))
        detail = result_files[0].read_text(encoding="utf-8") if result_files else ""
        if "ERR_BLOCKED_BY_ADMINISTRATOR" in detail:
            pytest.skip("Execution environment blocks browser navigation to localhost")
    assert code == 0
