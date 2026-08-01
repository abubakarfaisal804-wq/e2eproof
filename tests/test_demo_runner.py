from __future__ import annotations

from scripts.demo_runner import wait_until_ready


def test_wait_until_ready_against_real_demo_server(demo_server: str) -> None:
    wait_until_ready(f"{demo_server}/health", timeout_seconds=2)
