from __future__ import annotations

import json
import mimetypes
import os
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .auth import SESSION_SECONDS, AuthError, AuthStore
from .store import Conflict, NotesStore, StoreError


APP_DIR = Path(__file__).parent
STATIC_DIR = APP_DIR / "static"
DEFAULT_NOTES_ROOT = APP_DIR.parent / "synthetic_data" / "Coaching notes"
STORE = NotesStore(os.environ.get("NOTES_ROOT", DEFAULT_NOTES_ROOT))
DATA_DIR = os.environ.get("HEARTHNOTE_DATA_DIR", APP_DIR.parent / ".hearthnote")
AUTH = AuthStore(DATA_DIR)
SESSION_COOKIE = "hearthnote_session"
SECURE_COOKIE = os.environ.get("HEARTHNOTE_SECURE_COOKIE") == "1"


class Handler(BaseHTTPRequestHandler):
    server_version = "Hearthnote/0.1"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/auth/status":
                return self._json(200, {
                    "setup_required": AUTH.setup_required(),
                    "authenticated": AUTH.authenticated(self._session_token()),
                })
            if path.startswith("/api/"):
                self._require_session()
            if path == "/api/clients":
                return self._json(200, {"clients": STORE.list_clients()})
            match = self._match_client_path(path)
            if match and match[1] is None:
                return self._json(200, {"sessions": STORE.list_sessions(match[0])})
            if match and match[1] is not None:
                return self._json(200, STORE.read_session(match[0], match[1]))
            other_note = self._match_other_notes_path(path)
            if other_note:
                client, filename = other_note
                if filename is None:
                    return self._json(200, {"notes": STORE.list_other_notes(client)})
                return self._json(200, STORE.read_other_note(client, filename))
            if path.startswith("/api/"):
                return self._json(404, {"error": "Not found"})
            return self._static(path)
        except (AuthError, StoreError) as error:
            self._request_error(error)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            self._require_same_origin()
            if path.startswith("/api/auth/") and self.headers.get_content_type() != "application/json":
                raise AuthError("Expected a JSON request.", 415)
            if path == "/api/auth/logout":
                AUTH.logout(self._session_token())
                return self._json(200, {"authenticated": False}, self._session_cookie("", 0))
            if path in {"/api/auth/setup", "/api/auth/login"}:
                payload = self._body(max_length=4096)
                create_account = path == "/api/auth/setup"
                authenticate = AUTH.setup if create_account else AUTH.login
                token = authenticate(payload.get("username"), payload.get("password"))
                return self._json(
                    201 if create_account else 200,
                    {"authenticated": True},
                    self._session_cookie(token, SESSION_SECONDS),
                )
            self._require_session()
            if path == "/api/clients":
                payload = self._body()
                return self._json(201, STORE.create_client(payload.get("name", "")))
            match = self._match_client_path(path)
            if match and match[1] is None:
                return self._json(201, STORE.create_session(match[0]))
            self._json(404, {"error": "Not found"})
        except (AuthError, StoreError) as error:
            self._request_error(error)

    def do_PUT(self) -> None:
        path = urlparse(self.path).path
        try:
            self._require_same_origin()
            self._require_session()
            match = self._match_client_path(path)
            if match and match[1] is not None:
                payload = self._body()
                result = STORE.update_session(
                    match[0], match[1], payload.get("content"), payload.get("etag", "")
                )
                return self._json(200, result)
            other_note = self._match_other_notes_path(path)
            if other_note and other_note[1] is not None:
                payload = self._body()
                result = STORE.update_other_note(
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
        if not AUTH.authenticated(self._session_token()):
            raise AuthError("Sign in to access your notes.", 401)

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
            if not 0 <= length <= max_length:
                raise StoreError("Invalid request length")
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            raise StoreError("Invalid JSON") from None
        if not isinstance(payload, dict):
            raise StoreError("Expected a JSON object")
        return payload

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
    print(f"Hearthnote is reading notes from {STORE.root}")
    print(f"Open http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    run()

