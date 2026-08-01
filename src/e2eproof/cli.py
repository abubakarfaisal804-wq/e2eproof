from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
import webbrowser
from pathlib import Path
from typing import Any, Literal

import yaml
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from . import __version__
from .ai import diagnose_result, draft_contract
from .config import load_contract, write_sample_contract
from .demo_server import serve
from .errors import E2EProofError
from .evidence import generate_keypair, verify_bundle
from .models import Contract
from .runner import find_browser_executable, run_contract

BrowserEngine = Literal["chromium", "firefox", "webkit"]
BROWSER_ENGINES: tuple[BrowserEngine, ...] = ("chromium", "firefox", "webkit")


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _add_demo_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--browser", choices=BROWSER_ENGINES, default="chromium")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("evidence"))
    parser.add_argument("--no-open", action="store_true", help="Do not open report.html")
    parser.add_argument("--json", action="store_true")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="e2eproof",
        description="Verify claimed web-app outcomes and produce tamper-evident evidence.",
    )
    parser.add_argument("--version", action="version", version=f"E2EProof {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create a conservative sample contract")
    init.add_argument("path", nargs="?", default="e2eproof.yaml")
    init.add_argument("--force", action="store_true")

    validate = sub.add_parser("validate", help="Validate a contract without executing it")
    validate.add_argument("contract")
    validate.add_argument("--json", action="store_true")

    run = sub.add_parser("run", help="Execute a contract")
    run.add_argument("contract")
    run.add_argument("--output", type=Path)
    run.add_argument("--run-id")
    run.add_argument("--headed", action="store_true")
    run.add_argument("--browser", choices=BROWSER_ENGINES)
    run.add_argument("--browser-path")
    run.add_argument("--sign-key")
    run.add_argument("--json", action="store_true")

    verify = sub.add_parser("verify", help="Verify hashes, event chain and optional signature")
    verify.add_argument("bundle", type=Path)
    verify.add_argument("--public-key", type=Path, help="Require this trusted Ed25519 signer")
    verify.add_argument("--json", action="store_true")

    keygen = sub.add_parser("keygen", help="Generate an Ed25519 signing keypair")
    keygen.add_argument("directory", type=Path)
    keygen.add_argument("--force", action="store_true")

    doctor = sub.add_parser("doctor", help="Check runtime prerequisites")
    doctor.add_argument("--contract", type=Path)
    doctor.add_argument("--browser", choices=BROWSER_ENGINES)
    doctor.add_argument("--json", action="store_true")

    install_browser = sub.add_parser(
        "install-browser",
        help="Install a Playwright browser used by E2EProof",
    )
    install_browser.add_argument(
        "browser", choices=(*BROWSER_ENGINES, "all"), nargs="?", default="chromium"
    )
    install_browser.add_argument(
        "--with-deps", action="store_true", help="Also install Linux OS dependencies"
    )

    demo = sub.add_parser("demo", help="Run a real local browser-to-backend proof")
    _add_demo_options(demo)

    quickstart = sub.add_parser(
        "quickstart",
        help="Install a missing browser (with confirmation) and run the real demo",
    )
    _add_demo_options(quickstart)
    quickstart.add_argument(
        "-y", "--yes", action="store_true", help="Install a missing browser without prompting"
    )

    schema = sub.add_parser("schema", help="Write the JSON schema for contracts")
    schema.add_argument("--output", type=Path)

    ai_draft = sub.add_parser("ai-draft", help="Draft then validate a contract with OpenAI")
    ai_draft.add_argument("--base-url", required=True)
    ai_draft.add_argument("--claim", required=True)
    ai_draft.add_argument("--requirements-file", type=Path)
    ai_draft.add_argument("--model", default="gpt-5.6-sol")
    ai_draft.add_argument("--effort", choices=["low", "medium", "high", "xhigh"], default="high")
    ai_draft.add_argument("--output", type=Path, default=Path("e2eproof.ai.yaml"))

    ai_diag = sub.add_parser("ai-diagnose", help="Diagnose a redacted result with OpenAI")
    ai_diag.add_argument("result", type=Path)
    ai_diag.add_argument("--model", default="gpt-5.6-sol")
    ai_diag.add_argument("--effort", choices=["low", "medium", "high", "xhigh"], default="high")
    ai_diag.add_argument("--output", type=Path)
    return parser


def _browser_doctor_detail(engine: BrowserEngine = "chromium") -> tuple[bool, str]:
    system_browser = find_browser_executable(engine)
    if system_browser:
        return True, system_browser
    try:
        with sync_playwright() as playwright:
            browser_type = getattr(playwright, engine)
            managed = Path(browser_type.executable_path)
            if managed.is_file():
                return True, str(managed)
    except PlaywrightError as error:
        return False, f"Playwright unavailable: {error}"
    return False, f"Not found. Run: e2eproof install-browser {engine}"


def _doctor(
    contract_path: Path | None, browser_engine: BrowserEngine | None = None
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    checks.append(
        {"name": "python", "ok": sys.version_info >= (3, 11), "detail": sys.version.split()[0]}
    )

    contract: Contract | None = None
    if contract_path:
        try:
            contract = load_contract(contract_path)
            checks.append({"name": "contract", "ok": True, "detail": contract.name})
            missing = [
                spec.env
                for spec in contract.secrets.values()
                if spec.required and not os.getenv(spec.env)
            ]
            checks.append(
                {
                    "name": "required-secrets",
                    "ok": not missing,
                    "detail": "all set" if not missing else "missing: " + ", ".join(missing),
                }
            )
        except E2EProofError as error:
            checks.append({"name": "contract", "ok": False, "detail": str(error)})

    selected_engine: BrowserEngine = browser_engine or (
        contract.browser.engine if contract else "chromium"
    )
    browser_ok, browser_detail = _browser_doctor_detail(selected_engine)
    checks.append(
        {
            "name": f"{selected_engine}-browser",
            "ok": browser_ok,
            "detail": browser_detail,
        }
    )
    checks.append(
        {
            "name": "openai-key-optional",
            "ok": bool(os.getenv("OPENAI_API_KEY")),
            "required": False,
            "detail": "set"
            if os.getenv("OPENAI_API_KEY")
            else "not set; core verification still works",
        }
    )
    required_failures = [item for item in checks if item.get("required", True) and not item["ok"]]
    return {
        "ok": not required_failures,
        "product_version": __version__,
        "platform": platform.platform(),
        "browser": selected_engine,
        "checks": checks,
    }


def _install_browser(engine: str, *, with_deps: bool = False) -> None:
    engines = list(BROWSER_ENGINES) if engine == "all" else [engine]
    for selected in engines:
        command = [sys.executable, "-m", "playwright", "install"]
        if with_deps:
            command.append("--with-deps")
        command.append(selected)
        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            raise OSError(
                f"Browser installation failed for {selected} (exit {completed.returncode})"
            )


def _demo_contract(base_url: str, output: Path, engine: BrowserEngine, headed: bool) -> Contract:
    return Contract.model_validate(
        {
            "version": 1,
            "name": f"E2EProof real {engine} quickstart",
            "description": "A real browser action plus independent backend read-back.",
            "base_url": base_url,
            "variables": {"email": "quickstart+{{run_id}}@example.com"},
            "browser": {"engine": engine, "headless": not headed},
            "policy": {
                "allowed_hosts": ["127.0.0.1", "localhost"],
                "fail_on_console_error": True,
                "fail_on_page_error": True,
                "fail_on_request_failure": True,
                "forbidden_visible_markers": ["demo mode", "mock response", "fallback active"],
            },
            "evidence": {
                "output_dir": str(output),
                "screenshot": "failure",
                "trace": "failure",
                "include_console": True,
                "include_network": True,
            },
            "flows": [
                {
                    "id": "lead-capture",
                    "claim": "Submitting the form stores exactly one lead and shows a real confirmation.",
                    "steps": [
                        {"type": "browser.goto", "url": "/app/real"},
                        {
                            "type": "browser.fill",
                            "target": {"label": "Email"},
                            "value": "{{email}}",
                        },
                        {
                            "type": "browser.click",
                            "target": {"role": "button", "name": "Submit lead"},
                        },
                        {
                            "type": "browser.assert_text",
                            "target": "#status",
                            "contains": "Saved",
                        },
                        {
                            "type": "network.assert",
                            "kind": "response",
                            "url_contains": "/api/leads",
                            "method": "POST",
                            "status": 201,
                            "minimum": 1,
                            "maximum": 1,
                        },
                        {
                            "type": "http.poll",
                            "method": "GET",
                            "url": "/api/leads?email={{email}}",
                            "poll_timeout_ms": 5000,
                            "interval_ms": 250,
                            "assertions": {
                                "status": 200,
                                "json": [
                                    {"path": "$.count", "equals": 1},
                                    {"path": "$.items[0].email", "equals": "{{email}}"},
                                ],
                            },
                        },
                    ],
                }
            ],
        }
    )


def _run_demo(
    *, engine: BrowserEngine, headed: bool, output: Path, no_open: bool, json_output: bool
) -> int:
    server = serve("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, name="e2eproof-demo", daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        contract = _demo_contract(f"http://{host}:{port}", output, engine, headed)
        with tempfile.TemporaryDirectory(prefix="e2eproof-demo-") as temporary:
            contract_path = Path(temporary) / "quickstart.yaml"
            contract_path.write_text(
                yaml.safe_dump(
                    contract.model_dump(mode="json", by_alias=True),
                    sort_keys=False,
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            result, bundle = run_contract(contract, contract_path=contract_path, output_dir=output)
        report = (bundle / "report.html").resolve()
        payload = {
            "status": result.status,
            "browser": engine,
            "bundle": str(bundle),
            "report": str(report),
            "summary": result.summary,
        }
        if json_output:
            _print_json(payload)
        else:
            print(f"{result.status.upper()}: real {engine} browser-to-backend proof")
            print(f"Evidence: {bundle}")
            print(f"Report:   {report}")
        if result.status == "passed" and not no_open:
            with contextlib.suppress(webbrowser.Error):
                webbrowser.open(report.as_uri())
        return 0 if result.status == "passed" else 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _confirm_browser_install(engine: BrowserEngine, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        return False
    answer = (
        input(f"{engine} is missing. Install it now (roughly a few hundred MB)? [Y/n] ")
        .strip()
        .casefold()
    )
    return answer in {"", "y", "yes", "j", "ja"}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "init":
            path = write_sample_contract(args.path, force=args.force)
            print(f"Created {path}")
            return 0

        if args.command == "validate":
            contract = load_contract(args.contract)
            payload = {"valid": True, "name": contract.name, "flows": len(contract.flows)}
            _print_json(payload) if args.json else print(
                f"VALID: {contract.name} ({len(contract.flows)} flows)"
            )
            return 0

        if args.command == "run":
            contract = load_contract(args.contract)
            updates: dict[str, Any] = {}
            browser_updates: dict[str, Any] = {}
            if args.headed:
                browser_updates["headless"] = False
            if args.browser:
                browser_updates["engine"] = args.browser
                if args.browser != "chromium" and not args.browser_path:
                    browser_updates["executable_path"] = None
                    browser_updates["channel"] = None
            if args.browser_path:
                browser_updates["executable_path"] = args.browser_path
            if browser_updates:
                updates["browser"] = contract.browser.model_copy(update=browser_updates)
            if args.sign_key:
                updates["evidence"] = contract.evidence.model_copy(
                    update={"sign_key": args.sign_key}
                )
            if updates:
                contract = contract.model_copy(update=updates)
            result, bundle = run_contract(
                contract,
                contract_path=Path(args.contract),
                output_dir=args.output,
                run_id=args.run_id,
            )
            payload = {"status": result.status, "bundle": str(bundle), "summary": result.summary}
            if args.json:
                _print_json(payload)
            else:
                print(f"{result.status.upper()}: {result.contract_name}")
                print(f"Evidence: {bundle}")
                print(f"Report:   {bundle / 'report.html'}")
            return 0 if result.status == "passed" else 1

        if args.command == "verify":
            summary = verify_bundle(args.bundle, trusted_public_key=args.public_key)
            payload = {
                "valid": summary.valid,
                "bundle": summary.bundle,
                "files_checked": summary.files_checked,
                "signature_present": summary.signature_present,
                "signature_valid": summary.signature_valid,
                "trusted_key_match": summary.trusted_key_match,
                "event_chain_valid": summary.event_chain_valid,
                "errors": summary.errors,
                "warnings": summary.warnings,
            }
            if args.json:
                _print_json(payload)
            else:
                print("VALID" if summary.valid else "INVALID")
                for error in summary.errors:
                    print(f"ERROR: {error}")
                for warning in summary.warnings:
                    print(f"WARNING: {warning}")
            return 0 if summary.valid else 3

        if args.command == "keygen":
            private_key, public_key = generate_keypair(args.directory, force=args.force)
            print(f"Private key: {private_key}")
            print(f"Public key:  {public_key}")
            return 0

        if args.command == "doctor":
            payload = _doctor(args.contract, args.browser)
            if args.json:
                _print_json(payload)
            else:
                for check in payload["checks"]:
                    mark = (
                        "OK"
                        if check["ok"]
                        else ("INFO" if check.get("required") is False else "FAIL")
                    )
                    print(f"[{mark}] {check['name']}: {check['detail']}")
            return 0 if payload["ok"] else 2

        if args.command == "install-browser":
            _install_browser(args.browser, with_deps=args.with_deps)
            print(f"Installed browser selection: {args.browser}")
            return 0

        if args.command == "demo":
            return _run_demo(
                engine=args.browser,
                headed=args.headed,
                output=args.output,
                no_open=args.no_open,
                json_output=args.json,
            )

        if args.command == "quickstart":
            available, detail = _browser_doctor_detail(args.browser)
            if not available:
                if not _confirm_browser_install(args.browser, args.yes):
                    print(
                        f"Browser missing: {detail}\nRun 'e2eproof install-browser {args.browser}' and retry.",
                        file=sys.stderr,
                    )
                    return 2
                _install_browser(args.browser)
            return _run_demo(
                engine=args.browser,
                headed=args.headed,
                output=args.output,
                no_open=args.no_open,
                json_output=args.json,
            )

        if args.command == "schema":
            schema = Contract.model_json_schema()
            text = json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(text + "\n", encoding="utf-8")
                print(f"Wrote {args.output}")
            else:
                print(text)
            return 0

        if args.command == "ai-draft":
            requirements = ""
            if args.requirements_file:
                requirements = args.requirements_file.read_text(encoding="utf-8")
            contract = draft_contract(
                claim=args.claim,
                base_url=args.base_url,
                requirements=requirements,
                model=args.model,
                effort=args.effort,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                yaml.safe_dump(
                    contract.model_dump(mode="json", by_alias=True),
                    sort_keys=False,
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            print(f"Generated and validated {args.output}")
            return 0

        if args.command == "ai-diagnose":
            text = diagnose_result(args.result, model=args.model, effort=args.effort)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(text, encoding="utf-8")
                print(f"Wrote {args.output}")
            else:
                print(text)
            return 0

        return 2
    except (E2EProofError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
