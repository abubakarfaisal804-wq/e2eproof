from __future__ import annotations

import argparse
import json
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

STORE_LOCK = threading.Lock()
LEADS: list[dict[str, str]] = []
FLAKY_COUNT = 0


def _page(mode: str) -> str:
    inaccessible = mode == "inaccessible"
    label = "" if inaccessible else '<label for="email">Email</label>'
    lang = "" if inaccessible else ' lang="en"'
    title = "" if inaccessible else "<title>E2EProof demo</title>"
    button_text = "" if inaccessible else "Submit lead"
    script = {
        "real": "submitOnce('/api/leads')",
        "fake-success": "document.querySelector('#status').textContent='Saved';",
        "duplicate": "Promise.all([submitOnce('/api/leads'),submitOnce('/api/leads')])",
        "fallback": "fetch('/api/provider').then(async r=>{const x=await r.json(); document.querySelector('#status').textContent='OpenAI active: '+x.message;})",
        "console-error": "console.error('intentional demo console error'); submitOnce('/api/leads')",
        "request-failure": "fetch('http://127.0.0.1:1/unreachable'); submitOnce('/api/leads')",
        "inaccessible": "submitOnce('/api/leads')",
        "flaky": "submitOnce('/api/flaky')",
    }.get(mode, "submitOnce('/api/leads')")
    return f"""<!doctype html><html{lang}><head>{title}
<style>body{{font-family:system-ui;max-width:540px;margin:60px auto;padding:20px}}input,button{{padding:10px;margin:7px 0}}#status{{min-height:24px}}</style></head>
<body><h1>Lead capture</h1>{label}<input id="email" type="email"><button id="submit" aria-label="{button_text}">{button_text}</button><p id="status"></p>
<script>
async function submitOnce(path){{const email=document.querySelector('#email').value; const r=await fetch(path,{{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify({{email}})}}); const j=await r.json(); document.querySelector('#status').textContent=r.ok?'Saved':(j.message||'Failed');}}
document.querySelector('#submit').addEventListener('click',()=>{{{script}}});
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "E2EProofDemo/1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: object) -> None:
        self._send(status, json.dumps(payload).encode(), "application/json")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/app/"):
            self._send(200, _page(parsed.path.rsplit("/", 1)[-1]).encode(), "text/html; charset=utf-8")
            return
        if parsed.path == "/api/leads":
            email = parse_qs(parsed.query).get("email", [None])[0]
            with STORE_LOCK:
                items = [item for item in LEADS if email is None or item["email"] == email]
            self._json(200, {"count": len(items), "items": items})
            return
        if parsed.path == "/api/provider":
            self._json(503, {"message": "fallback active", "provider": "mock"})
            return
        if parsed.path == "/health":
            self._json(200, {"ok": True})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        global FLAKY_COUNT
        length = int(self.headers.get("Content-Length", "0"))
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid json"})
            return
        if self.path == "/api/reset":
            with STORE_LOCK:
                LEADS.clear()
                FLAKY_COUNT = 0
            self._json(200, {"ok": True})
            return
        if self.path == "/api/flaky":
            with STORE_LOCK:
                FLAKY_COUNT += 1
                count = FLAKY_COUNT
            if count == 1:
                self._json(503, {"message": "temporary failure"})
                return
        if self.path in {"/api/leads", "/api/flaky"}:
            email = str(data.get("email", "")).strip()
            if "@" not in email:
                self._json(422, {"message": "invalid email"})
                return
            with STORE_LOCK:
                item = {"id": str(len(LEADS) + 1), "email": email}
                LEADS.append(item)
            self._json(201, item)
            return
        self._json(404, {"error": "not found"})


def serve(host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), Handler)
    return server


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = serve(args.host, args.port)
    print(f"Demo server: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
