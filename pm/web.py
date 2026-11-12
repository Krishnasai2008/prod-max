"""The local HTTP server behind pm ui: same-origin guard, static page, JSON API."""
import json
import re
import traceback
from collections.abc import Callable, Mapping
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from pm.api import Raw, handle
from pm.db import connect

PORT = 8321
UI = Path(__file__).parent / "ui"

CSP = ("default-src 'self'; script-src 'self' https://cdn.jsdelivr.net/npm/mathjax@3.2.2/; "
       "style-src 'self' 'unsafe-inline'; "
       "font-src 'self' https://cdn.jsdelivr.net/npm/mathjax@3.2.2/; "
       "img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
MAX_BODY = 65536
_NAME = re.compile(r"[a-z0-9_-]+\.(html|css|js|svg)")
_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css",
          ".js": "text/javascript", ".svg": "image/svg+xml"}


def _header(headers: Mapping[str, str], name: str) -> str | None:
    value = headers.get(name)
    if value is not None:
        return value
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return None


def check(method: str, headers: Mapping[str, str], port: int) -> str | None:
    if method not in ("GET", "POST"):
        return "use GET or POST"
    host = _header(headers, "Host")
    if host not in (f"127.0.0.1:{port}", f"localhost:{port}"):
        return "bad host"
    origin = _header(headers, "Origin")
    if origin is not None and origin not in (f"http://127.0.0.1:{port}",
                                             f"http://localhost:{port}"):
        return "bad origin"
    if method == "POST":
        content_type = _header(headers, "Content-Type")
        if content_type is None or not content_type.startswith("application/json"):
            return "send json"
    return None


# shortcut: any program on this machine can call the API, add a token if the laptop is shared
def make_server(db_path: str | Path, port: int,
                now: Callable[[], datetime]) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_PUT(self):
            self._dispatch("PUT")

        def do_DELETE(self):
            self._dispatch("DELETE")

        def do_PATCH(self):
            self._dispatch("PATCH")

        def do_OPTIONS(self):
            self._dispatch("OPTIONS")

        def do_HEAD(self):
            self._dispatch("HEAD")

        def _dispatch(self, method: str) -> None:
            target = urlsplit(self.path)
            path = target.path
            try:
                reason = check(method, self.headers, self.server.server_port)
                if reason is not None:
                    status = 405 if reason == "use GET or POST" else 403
                    self._send(status, {"error": reason}, path)
                elif path.startswith("/api/"):
                    self._api(method, path, target.query)
                elif method == "GET":
                    self._file(path)
                else:
                    self._send(404, {"error": "no such route"}, path)
            except Exception:
                traceback.print_exc()
                try:
                    self._send(500, {"error": "internal error"}, path)
                except Exception:
                    pass

        def _api(self, method: str, path: str, query_string: str) -> None:
            body: dict = {}
            if method == "POST":
                raw_length = self.headers.get("Content-Length")
                try:
                    length = max(0, int(raw_length)) if raw_length else 0
                except ValueError:
                    length = 0
                if length > MAX_BODY:
                    self._send(413, {"error": "too large"}, path)
                    return
                if length:
                    try:
                        body = json.loads(self.rfile.read(length))
                    except ValueError:
                        self._send(400, {"error": "send a json object"}, path)
                        return
                    if not isinstance(body, dict):
                        self._send(400, {"error": "send a json object"}, path)
                        return
            query = {key: values[-1] for key, values in parse_qs(query_string).items()}
            conn = connect(db_path)
            try:
                status, data = handle(conn, method, path, query, body, now())
            finally:
                conn.close()
            self._send(status, data, path)

        def _file(self, path: str) -> None:
            if path == "/":
                file = UI / "index.html"
            elif path.startswith("/ui/"):
                name = path[len("/ui/"):]
                if not _NAME.fullmatch(name) or not (UI / name).is_file():
                    self._send(404, {"error": "no such route"}, path)
                    return
                file = UI / name
            else:
                self._send(404, {"error": "no such route"}, path)
                return
            self._send(200, file.read_bytes(), path, _TYPES[file.suffix])

        def _send(self, status: int, payload, path: str, content_type=None) -> None:
            max_age = 0
            if isinstance(payload, Raw):
                data = payload.data
                content_type = payload.content_type
                max_age = payload.max_age
            elif isinstance(payload, dict):
                data = json.dumps(payload).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            else:
                data = payload
            self.send_response(status)
            self.send_header("Content-Type", content_type or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            cache = "no-store" if path.startswith("/api/") else "no-cache"
            if max_age > 0:
                cache = f"private, max-age={max_age}"
            self.send_header("Cache-Control", cache)
            self.send_header("Content-Security-Policy", CSP)
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def serve(db_path: str | Path, port: int, now: Callable[[], datetime]) -> int:
    server = make_server(db_path, port, now)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0
