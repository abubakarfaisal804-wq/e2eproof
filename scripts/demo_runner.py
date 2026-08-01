from __future__ import annotations

import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from demo.server import serve  # noqa: E402
from e2eproof.config import load_contract  # noqa: E402
from e2eproof.errors import E2EProofError  # noqa: E402
from e2eproof.runner import run_contract  # noqa: E402


def wait_until_ready(url: str, timeout_seconds: float = 8.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1) as response:  # noqa: S310 - fixed local URL
                if response.status == 200:
                    return
        except (OSError, URLError) as error:
            last_error = error
        time.sleep(0.1)
    raise RuntimeError(f"Demo server did not become ready: {last_error}")


def main() -> int:
    server = serve()
    thread = threading.Thread(target=server.serve_forever, name="e2eproof-demo", daemon=True)
    thread.start()
    try:
        wait_until_ready("http://127.0.0.1:8765/health")
        contract_path = ROOT / "examples" / "real.yaml"
        contract = load_contract(contract_path)
        result, bundle = run_contract(contract, contract_path=contract_path)
        report = (bundle / "report.html").resolve()
        print(f"{result.status.upper()}: {result.contract_name}")
        print(f"Evidence: {bundle}")
        print(f"Report:   {report}")
        try:
            webbrowser.open(report.as_uri())
        except webbrowser.Error:
            pass
        return 0 if result.status == "passed" else 1
    except (E2EProofError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
