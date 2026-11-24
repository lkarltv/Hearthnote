from __future__ import annotations

import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .config import VaultManager
from .knowledge import list_topics, read_material
from .store import Conflict, StoreError


APP_DIR = Path(__file__).parent
STATIC_DIR = APP_DIR / "static"
DEFAULT_NOTES_ROOT = APP_DIR.parent / "synthetic_data"
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "hearthnote" / "settings.json"
VAULT = VaultManager(
    os.environ.get("NOTES_ROOT", DEFAULT_NOTES_ROOT),
    os.environ.get("CONFIG_PATH", DEFAULT_CONFIG_PATH),
    os.environ.get("VAULT_BOUNDARY"),
)


class Handler(BaseHTTPRequestHandler):
    server_version = "Hearthnote/0.1"

    def do_GET(self) -> None:
        request = urlparse(self.path)
        path = request.path
        query = parse_qs(request.query, keep_blank_values=True)
        source = query.get("source", [None])[0]
        try:
            if path == "/api/clients":
                return self._json(200, {"clients": VAULT.client_store(source).list_clients()})
            if path == "/api/settings":
                return self._json(200, VAULT.details())
            if path == "/api/folders":
                return self._json(200, VAULT.browse(
                    query.get("root", [None])[0], query.get("parent", ["."])[0],
                ))
            if path == "/api/knowledge":
                return self._json(200, {"topics": list_topics(VAULT.source_folder("knowledge", source))})
            if path == "/api/material":
                return self._json(200, read_material(
                    VAULT.source_folder("knowledge", source), query.get("path", [""])[0],
                ))
            match = self._match_client_path(path)
            if match and match[1] is None:
                return self._json(200, {"sessions": VAULT.client_store(source).list_sessions(match[0])})
            if match and match[1] is not None:
                return self._json(200, VAULT.client_store(source).read_session(match[0], match[1]))
            if path.startswith("/api/"):
                return self._json(404, {"error": "Not found"})
            return self._static(path)
        except StoreError as error:
            self._store_error(error)

    def do_POST(self) -> None:
        request = urlparse(self.path)
        path = request.path
        query = parse_qs(request.query, keep_blank_values=True)
        source = query.get("source", [None])[0]
        try:
            if path == "/api/clients":
                payload = self._body()
                return self._json(201, VAULT.client_store(source).create_client(payload.get("name", "")))
            match = self._match_client_path(path)
            if match and match[1] is None:
                return self._json(201, VAULT.client_store(source).create_session(match[0]))
            self._json(404, {"error": "Not found"})
        except StoreError as error:
            self._store_error(error)

    def do_PUT(self) -> None:
        request = urlparse(self.path)
        path = request.path
        query = parse_qs(request.query, keep_blank_values=True)
        source = query.get("source", [None])[0]
        try:
            if path == "/api/settings":
                payload = self._body()
                return self._json(200, VAULT.update(payload.get("notes_root"), payload.get("sources")))
            match = self._match_client_path(path)
            if match and match[1] is not None:
                payload = self._body()
                result = VAULT.client_store(source).update_session(
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
            payload = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(payload, dict):
                raise StoreError("Invalid JSON")
            return payload
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
    print(f"Hearthnote is reading notes from {VAULT.details()['notes_root']}")
    print(f"Open http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    run()

