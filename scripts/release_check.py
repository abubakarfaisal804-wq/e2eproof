from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = {**os.environ, "PYTHONPATH": f"{ROOT / 'src'}{os.pathsep}{ROOT}"}


def run(*args: str) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, cwd=ROOT, env=ENV, check=True)


def validate_examples() -> None:
    # Validate all shipped contracts in one Python process. Starting the CLI once
    # per file is needlessly slow on some Windows and sandbox environments.
    sys.path.insert(0, str(ROOT / "src"))
    from e2eproof.config import load_contract

    contracts = sorted((ROOT / "examples").glob("*.yaml"))
    for contract_path in contracts:
        contract = load_contract(contract_path)
        print(f"VALID: {contract.name} ({len(contract.flows)} flows)", flush=True)


def main() -> int:
    run(sys.executable, "-m", "compileall", "-q", "src", "tests", "demo", "scripts")
    run(sys.executable, "scripts/static_audit.py")
    run(
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--cov=e2eproof",
        "--cov-report=term-missing",
    )
    validate_examples()
    run(sys.executable, "-m", "pip", "wheel", ".", "--no-build-isolation", "--no-deps", "-w", "dist")
    print("Release checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
