from __future__ import annotations

import html
import json
from pathlib import Path
from xml.etree.ElementTree import Element, ElementTree, SubElement

from .results import RunResult

_STATUS_CLASS = {
    "passed": "pass",
    "failed": "fail",
    "flaky": "flaky",
    "skipped": "skip",
}


def generate_html_report(result: RunResult) -> str:
    flow_sections: list[str] = []
    for flow in result.flows:
        attempts_html: list[str] = []
        for attempt in flow.attempts:
            rows: list[str] = []
            for step in attempt.steps:
                artifact_links = " ".join(
                    f'<a href="{html.escape(path)}">{html.escape(Path(path).name)}</a>'
                    for path in step.artifacts
                )
                details = ""
                if step.details:
                    details = (
                        "<details><summary>Details</summary><pre>"
                        + html.escape(json.dumps(step.details, ensure_ascii=False, indent=2))
                        + "</pre></details>"
                    )
                rows.append(
                    "<tr>"
                    f"<td>{step.index + 1}</td>"
                    f"<td><code>{html.escape(step.type)}</code></td>"
                    f'<td><span class="pill {_STATUS_CLASS[step.status]}">{step.status}</span></td>'
                    f"<td>{step.duration_ms} ms</td>"
                    f"<td>{html.escape(step.message)}{details}</td>"
                    f"<td>{artifact_links}</td>"
                    "</tr>"
                )
            attempts_html.append(
                f"<details {'open' if attempt.status == 'failed' else ''}>"
                f"<summary>Attempt {attempt.attempt}: {attempt.status} · {attempt.duration_ms} ms</summary>"
                '<div class="table-wrap"><table><thead><tr>'
                "<th>#</th><th>Step</th><th>Status</th><th>Time</th><th>Result</th><th>Evidence</th>"
                "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div></details>"
            )
        flow_sections.append(
            f'<section class="flow {_STATUS_CLASS[flow.status]}">'
            f'<div class="flow-head"><div><h2>{html.escape(flow.id)}</h2>'
            f"<p>{html.escape(flow.claim)}</p></div>"
            f'<span class="pill {_STATUS_CLASS[flow.status]}">{flow.status}</span></div>'
            + "".join(attempts_html)
            + "</section>"
        )

    summary_cards = "".join(
        f'<div class="metric"><strong>{value}</strong><span>{html.escape(key)}</span></div>'
        for key, value in result.summary.items()
    )
    policy = "".join(f"<li>{html.escape(item)}</li>" for item in result.policy_findings)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>E2EProof report — {html.escape(result.contract_name)}</title>
<style>
:root{{--bg:#07111f;--panel:#0d1b2d;--text:#ecf3fb;--muted:#9fb0c4;--line:#22364e;--pass:#33d17a;--fail:#ff6b6b;--flaky:#ffbf47;--skip:#8b9aae}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{width:min(1200px,calc(100% - 32px));margin:0 auto;padding:44px 0 80px}}h1{{font-size:clamp(2rem,5vw,4rem);letter-spacing:-.05em;margin:.2em 0}}h2{{margin:0;font-size:1.2rem}}p{{color:var(--muted)}}code,pre{{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}}pre{{white-space:pre-wrap;word-break:break-word;background:#06101d;padding:14px;border-radius:10px;max-height:420px;overflow:auto}}
.hero{{border:1px solid var(--line);background:linear-gradient(145deg,#0f233a,#0a1727);padding:30px;border-radius:24px}}
.meta{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px;margin-top:20px;color:var(--muted)}}.meta b{{color:var(--text)}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin:24px 0}}.metric{{border:1px solid var(--line);background:var(--panel);padding:18px;border-radius:16px}}.metric strong{{display:block;font-size:1.8rem}}.metric span{{color:var(--muted)}}
.flow{{border:1px solid var(--line);background:var(--panel);padding:20px;border-radius:20px;margin:16px 0}}.flow.pass{{border-left:5px solid var(--pass)}}.flow.fail{{border-left:5px solid var(--fail)}}.flow.flaky{{border-left:5px solid var(--flaky)}}
.flow-head{{display:flex;justify-content:space-between;gap:18px;align-items:flex-start}}.pill{{display:inline-block;padding:4px 9px;border-radius:999px;font-size:.76rem;font-weight:800;text-transform:uppercase;letter-spacing:.05em}}.pill.pass{{background:#143d2b;color:#8ff0b8}}.pill.fail{{background:#471d25;color:#ffadb2}}.pill.flaky{{background:#493819;color:#ffd98c}}.pill.skip{{background:#273240;color:#c3ceda}}
details{{border-top:1px solid var(--line);margin-top:14px;padding-top:13px}}summary{{cursor:pointer;font-weight:700}}.table-wrap{{overflow:auto;margin-top:12px}}table{{width:100%;border-collapse:collapse;min-width:850px}}th,td{{padding:11px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{color:var(--muted);font-size:.76rem;text-transform:uppercase;letter-spacing:.08em}}a{{color:#7cc4ff}}ul{{color:var(--muted)}}
</style></head>
<body><main>
<section class="hero">
<div class="pill {_STATUS_CLASS[result.status]}">{result.status}</div>
<h1>{html.escape(result.contract_name)}</h1>
<p>Contract-to-outcome verification report. A pass means every configured claim check passed under the recorded environment; it is not a proof of all possible behavior.</p>
<div class="meta">
<div><b>Run</b><br>{html.escape(result.run_id)}</div>
<div><b>Started</b><br>{html.escape(result.started_at)}</div>
<div><b>Duration</b><br>{result.duration_ms} ms</div>
<div><b>Contract SHA-256</b><br><code>{html.escape(result.contract_sha256)}</code></div>
</div></section>
<section class="metrics">{summary_cards}</section>
{('<section class="flow fail"><h2>Policy findings</h2><ul>' + policy + "</ul></section>") if policy else ""}
{"".join(flow_sections)}
</main></body></html>"""


def write_junit(result: RunResult, path: Path) -> None:
    tests = len(result.flows)
    failures = sum(flow.status == "failed" for flow in result.flows)
    skipped = sum(flow.status == "skipped" for flow in result.flows)
    suite = Element(
        "testsuite",
        {
            "name": result.contract_name,
            "tests": str(tests),
            "failures": str(failures),
            "skipped": str(skipped),
            "time": f"{result.duration_ms / 1000:.3f}",
        },
    )
    for flow in result.flows:
        case = SubElement(
            suite,
            "testcase",
            {
                "classname": "e2eproof",
                "name": flow.id,
                "time": f"{flow.duration_ms / 1000:.3f}",
            },
        )
        if flow.status == "failed":
            failure = SubElement(case, "failure", {"message": "Outcome claim failed"})
            last_attempt = flow.attempts[-1]
            failure.text = last_attempt.failure or "One or more verification steps failed"
        elif flow.status == "skipped":
            SubElement(case, "skipped")
        elif flow.status == "flaky":
            output = SubElement(case, "system-out")
            output.text = "Flow passed only after retry and is classified as flaky."
    ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)
