from __future__ import annotations

import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .store import Conflict, NotesStore, StoreError


APP_DIR = Path(__file__).parent
STATIC_DIR = APP_DIR / "static"
DEFAULT_NOTES_ROOT = APP_DIR.parent / "synthetic_data" / "Coaching notes"
STORE = NotesStore(os.environ.get("NOTES_ROOT", DEFAULT_NOTES_ROOT))


class Handler(BaseHTTPRequestHandler):
    server_version = "Hearthnote/0.1"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/clients":
                return self._json(200, {"clients": STORE.list_clients()})
            match = self._match_client_path(path)
            if match and match[1] is None:
                return self._json(200, {"sessions": STORE.list_sessions(match[0])})
            if match and match[1] is not None:
                return self._json(200, STORE.read_session(match[0], match[1]))
            return self._static(path)
        except StoreError as error:
            self._store_error(error)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/clients":
                payload = self._body()
                return self._json(201, STORE.create_client(payload.get("name", "")))
            match = self._match_client_path(path)
            if match and match[1] is None:
                return self._json(201, STORE.create_session(match[0]))
            self._json(404, {"error": "Not found"})
        except StoreError as error:
            self._store_error(error)

    def do_PUT(self) -> None:
        path = urlparse(self.path).path
        try:
            match = self._match_client_path(path)
            if match and match[1] is not None:
                payload = self._body()
                result = STORE.update_session(
                    match[0], match[1], payload.get("content"), payload.get("etag", "")
                )
                return self._json(200, result)
            self._json(404, {"error": "Not found"})
        except StoreError as error:
            self._store_error(error)

    @staticmethod
    def _match_client_path(path: str) -> tuple[str, int | None] | None:
        parts = [unquote(part) for part in path.strip("/").split("/")]
        if len(parts) == 4 and parts[:2] == ["api", "clients"] and parts[3] == "sessions":
            return parts[2], None
        if len(parts) == 5 and parts[:2] == ["api", "clients"] and parts[3] == "sessions":
            try:
                return parts[2], int(parts[4])
            except ValueError:
                return None
        return None

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 2_100_000:
                raise StoreError("Request is too large")
            return json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            raise StoreError("Invalid JSON")

    def _static(self, path: str) -> None:
        relative = "index.html" if path in {"", "/"} else path.lstrip("/")
        candidate = (STATIC_DIR / relative).resolve()
        if STATIC_DIR.resolve() not in candidate.parents or not candidate.is_file():
            candidate = STATIC_DIR / "index.html"
        data = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _store_error(self, error: StoreError) -> None:
        body = {"error": str(error)}
        if isinstance(error, Conflict):
            body["current"] = error.current
        self._json(error.status, body)

    def _json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")


def run() -> None:
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    print(f"Hearthnote is reading notes from {STORE.root}")
    print(f"Open http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    run()

