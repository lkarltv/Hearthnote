from __future__ import annotations

import json
import mimetypes
import os
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import trash
from .auth import SESSION_SECONDS, AuthError, AuthStore
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
DATA_DIR = os.environ.get("HEARTHNOTE_DATA_DIR", APP_DIR.parent / ".hearthnote")
AUTH = AuthStore(DATA_DIR)
SESSION_COOKIE = "hearthnote_session"
SECURE_COOKIE = os.environ.get("HEARTHNOTE_SECURE_COOKIE") == "1"


class Handler(BaseHTTPRequestHandler):
    server_version = "Hearthnote/0.1"

    def do_GET(self) -> None:
        request = urlparse(self.path)
        path = request.path
        query = parse_qs(request.query, keep_blank_values=True)
        source = query.get("source", [None])[0]
        try:
            if path == "/api/auth/status":
                return self._json(200, AUTH.session_status(self._session_token()))
            if not path.startswith("/api/"):
                return self._static(path)
            self._require_session()
            if path == "/api/clients":
                return self._json(200, {"clients": VAULT.client_store(source).list_clients()})
            if path == "/api/settings":
                return self._json(200, VAULT.details())
            if path == "/api/security":
                return self._json(200, AUTH.security_settings())
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
            other_note = self._match_other_notes_path(path)
            if other_note:
                client, filename = other_note
                store = VAULT.client_store(source)
                if filename is None:
                    return self._json(200, {"notes": store.list_other_notes(client)})
                return self._json(200, store.read_other_note(client, filename))
            return self._json(404, {"error": "Not found"})
        except (AuthError, StoreError) as error:
            self._request_error(error)

    def do_POST(self) -> None:
        request = urlparse(self.path)
        path = request.path
        query = parse_qs(request.query, keep_blank_values=True)
        source = query.get("source", [None])[0]
        try:
            self._require_same_origin()
            if (path.startswith("/api/auth/") or path in {"/api/trash", "/api/trash/undo"}) and self.headers.get_content_type() != "application/json":
                raise AuthError("Expected a JSON request.", 415)
            token = self._session_token()
            if path == "/api/auth/logout":
                AUTH.logout(token)
                return self._json(200, AUTH.session_status(""), self._session_cookie("", 0))
            if path == "/api/auth/open":
                return self._json(200, AUTH.session_status(token, opening=True))
            if path == "/api/auth/activity":
                AUTH.require_session(token, activity=True)
                return self._json(200, AUTH.session_status(token))
            if path == "/api/auth/unlock":
                return self._json(200, AUTH.unlock(token, self._body(max_length=4096).get("pin")))
            if path in {"/api/auth/setup", "/api/auth/login"}:
                payload = self._body(max_length=4096)
                username, password = payload.get("username"), payload.get("password")
                create_account = path == "/api/auth/setup"
                token = AUTH.setup(username, password, pin=payload.get("pin")) if create_account else AUTH.login(username, password)
                return self._json(
                    201 if create_account else 200,
                    AUTH.session_status(token),
                    self._session_cookie(token, SESSION_SECONDS),
                )
            self._require_session()
            if path in {"/api/trash", "/api/trash/undo"}:
                payload = self._body(max_length=4096)
                self._require_session()
                if path == "/api/trash/undo":
                    return self._json(200, trash.restore(VAULT, source, payload))
                AUTH.require_delete_pin(payload.get("pin"))
                return self._json(200, trash.move(VAULT, source, payload))
            if path == "/api/clients":
                payload = self._body()
                return self._json(201, VAULT.client_store(source).create_client(payload.get("name", "")))
            match = self._match_client_path(path)
            if match and match[1] is None:
                return self._json(201, VAULT.client_store(source).create_session(match[0]))
            self._json(404, {"error": "Not found"})
        except (AuthError, StoreError) as error:
            self._request_error(error)

    def do_PUT(self) -> None:
        request = urlparse(self.path)
        path = request.path
        query = parse_qs(request.query, keep_blank_values=True)
        source = query.get("source", [None])[0]
        try:
            self._require_same_origin()
            self._require_session()
            if path == "/api/settings":
                payload = self._body()
                return self._json(200, VAULT.update(payload.get("notes_root"), payload.get("sources")))
            if path == "/api/security":
                if self.headers.get_content_type() != "application/json":
                    raise AuthError("Expected a JSON request.", 415)
                return self._json(200, AUTH.update_security(self._session_token(), self._body(max_length=4096)))
            match = self._match_client_path(path)
            if match and match[1] is not None:
                payload = self._body()
                result = VAULT.client_store(source).update_session(
                    match[0], match[1], payload.get("content"), payload.get("etag", "")
                )
                return self._json(200, result)
            other_note = self._match_other_notes_path(path)
            if other_note and other_note[1] is not None:
                payload = self._body()
                result = VAULT.client_store(source).update_other_note(
                    other_note[0], other_note[1], payload.get("content"), payload.get("etag", "")
                )
                return self._json(200, result)
            self._json(404, {"error": "Not found"})
        except (AuthError, StoreError) as error:
            self._request_error(error)

    def _require_same_origin(self) -> None:
        origin = self.headers.get("Origin")
        if origin is None:
            return
        try:
            parsed = urlparse(origin)
        except ValueError:
            raise AuthError("This request did not come from Hearthnote.", 403) from None
        if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != self.headers.get("Host", "").lower():
            raise AuthError("This request did not come from Hearthnote.", 403)

    def _session_token(self) -> str:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            return ""
        return cookie[SESSION_COOKIE].value if SESSION_COOKIE in cookie else ""

    def _require_session(self) -> None:
        AUTH.require_session(self._session_token())

    @staticmethod
    def _session_cookie(token: str, max_age: int) -> str:
        secure = "; Secure" if SECURE_COOKIE else ""
        return f"{SESSION_COOKIE}={token}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Strict{secure}"

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

    @staticmethod
    def _match_other_notes_path(path: str) -> tuple[str, str | None] | None:
        parts = [unquote(part) for part in path.strip("/").split("/")]
        if len(parts) in {4, 5} and parts[:2] == ["api", "clients"] and parts[3] == "other-notes":
            return parts[2], parts[4] if len(parts) == 5 else None
        return None

    def _body(self, max_length: int = 2_100_000) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0:
                raise StoreError("Invalid request length")
            if length > max_length:
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

    def _request_error(self, error: AuthError | StoreError) -> None:
        body = {"error": str(error)}
        if isinstance(error, Conflict):
            body["current"] = error.current
        self._json(error.status, body)

    def _json(self, status: int, payload: dict, cookie: str | None = None) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")


def run() -> None:
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    AUTH.initialize()
    print(f"Hearthnote is reading notes from {VAULT.details()['notes_root']}")
    print(f"Open http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    run()

