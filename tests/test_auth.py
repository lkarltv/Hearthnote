import io
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from app import server
from app.auth import AuthError, AuthStore
from app.config import VaultManager


PASSWORD = "cedar coffee on the balcony"


class MemoryConnection:
    def __init__(self, request):
        self.input = io.BytesIO(request)
        self.output = bytearray()

    def makefile(self, *args):
        return self.input

    def sendall(self, data):
        self.output.extend(data)


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.auth = AuthStore(folder / "data")
        self.auth.initialize()
        self.notes_root = folder / "notes"
        (self.notes_root / "Clients").mkdir(parents=True)
        self.vault = VaultManager(self.notes_root, folder / "settings.json")
        notes = self.vault.client_store()
        notes.create_client("Client X")
        notes.create_session("Client X")
        self.enterContext(patch.multiple(server, AUTH=self.auth, VAULT=self.vault, SECURE_COOKIE=True))
        self.enterContext(patch.object(server.Handler, "log_message"))

    def request(self, path, method="GET", *, payload=None, cookie=None, origin=None):
        body = json.dumps(payload).encode() if payload is not None else b""
        request = [
            f"{method} {path} HTTP/1.0",
            "Host: vault.local",
            "Content-Type: application/json",
            f"Content-Length: {len(body)}",
        ]
        if cookie:
            request.append(f"Cookie: {cookie}")
        if origin:
            request.append(f"Origin: {origin}")
        connection = MemoryConnection("\r\n".join(request).encode() + b"\r\n\r\n" + body)
        server.Handler(connection, ("127.0.0.1", 1), object())
        header, data = bytes(connection.output).split(b"\r\n\r\n", 1)
        first_line, *headers = header.decode().split("\r\n")
        return int(first_line.split()[1]), dict(line.split(": ", 1) for line in headers), json.loads(data)

    def test_setup_login_logout_and_notes_access(self):
        status_path = "/api/auth/status"
        credentials = {"username": "coach", "password": "cedar123"}
        status = self.request(status_path)[2]
        self.assertTrue(status["setup_required"])
        self.assertFalse(status["authenticated"])
        self.assertFalse(status["locked"])
        for method, path in [
            ("GET", "/api/clients"),
            ("GET", "/api/settings"),
            ("GET", "/api/security"),
            ("GET", "/api/folders"),
            ("GET", "/api/knowledge"),
            ("GET", "/api/material"),
            ("GET", "/api/clients/Client%20X/sessions"),
            ("GET", "/api/clients/Client%20X/sessions/1"),
            ("GET", "/api/clients/Client%20X/other-notes"),
            ("GET", "/api/clients/Client%20X/other-notes/Intake.md"),
            ("POST", "/api/clients"),
            ("POST", "/api/clients/Client%20X/sessions"),
            ("POST", "/api/auth/activity"),
            ("POST", "/api/trash"),
            ("POST", "/api/trash/undo"),
            ("PUT", "/api/settings"),
            ("PUT", "/api/security"),
            ("PUT", "/api/clients/Client%20X/sessions/1"),
            ("PUT", "/api/clients/Client%20X/other-notes/Intake.md"),
        ]:
            with self.subTest(method=method, path=path):
                self.assertEqual(self.request(path, method)[0], 401)

        self.assertEqual(self.request("/api/auth/setup", "POST", payload=credentials, origin="https://elsewhere.local")[0], 403)
        self.assertEqual(self.request("/api/auth/setup", "POST", payload={"username": "coach", "password": "cedar12"})[0], 400)
        status, headers, _ = self.request("/api/auth/setup", "POST", payload=credentials, origin="https://vault.local")
        self.assertEqual(status, 201)
        for attribute in ["Path=/", "HttpOnly", "SameSite=Strict", "Secure"]:
            self.assertIn(attribute, headers["Set-Cookie"])
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        status = self.request(status_path, cookie=cookie)[2]
        self.assertFalse(status["setup_required"])
        self.assertTrue(status["authenticated"])
        self.assertFalse(status["locked"])
        self.assertFalse(status["security"]["enabled"])
        self.assertEqual(self.request("/api/auth/setup", "POST", payload=credentials)[0], 409)
        self.assertEqual(self.request("/api/clients", cookie=cookie)[0], 200)
        self.assertEqual(self.request("/api/clients", "POST", payload={"name": "New client"},
                                      cookie=cookie, origin="https://elsewhere.local")[0], 403)
        self.assertEqual(self.request("/api/clients", "POST", payload={"name": "New client"},
                                      cookie=cookie, origin="https://vault.local")[0], 201)

        reopened = AuthStore(self.auth.directory)
        reopened.initialize()
        with patch.object(server, "AUTH", reopened):
            self.assertEqual(self.request("/api/clients", cookie=cookie)[0], 200)
            with closing(sqlite3.connect(reopened.path)) as database:
                stored_hash, = database.execute("SELECT password_hash FROM account").fetchone()
                stored_token, = database.execute("SELECT token_hash FROM sessions").fetchone()
            self.assertEqual(len(stored_hash), 32)
            self.assertNotEqual(stored_hash, credentials["password"].encode())
            self.assertNotEqual(stored_token, cookie.split("=", 1)[1].encode())

            status, headers, _ = self.request("/api/auth/logout", "POST", cookie=cookie)
            self.assertEqual(status, 200)
            self.assertIn("Max-Age=0", headers["Set-Cookie"])
            self.assertEqual(self.request("/api/clients", cookie=cookie)[0], 401)
            status = self.request(status_path)[2]
            self.assertFalse(status["setup_required"])
            self.assertFalse(status["authenticated"])
            self.assertFalse(status["locked"])
            self.assertEqual(self.request("/api/auth/login", "POST", payload={**credentials, "password": "incorrect"})[0], 401)
            status, headers, _ = self.request("/api/auth/login", "POST", payload=credentials)
            self.assertEqual(status, 200)
            self.assertNotEqual(headers["Set-Cookie"].split(";", 1)[0], cookie)

    def test_pin_guards_the_workspace_and_recoverable_deletion(self):
        credentials = {"username": "coach", "password": PASSWORD, "pin": "0123"}
        status, headers, _ = self.request("/api/auth/setup", "POST", payload=credentials)
        self.assertEqual(status, 201)
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        policy = {"enabled": True, "ask_on_open": True, "idle_minutes": 10, "require_on_delete": True}
        self.assertEqual(self.request("/api/security", "PUT", cookie=cookie,
                                      payload={**policy, "password": PASSWORD})[2], policy)
        status, _, body = self.request("/api/auth/open", "POST", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertTrue(body["locked"])
        self.assertEqual(self.request("/api/clients", cookie=cookie)[0], 423)
        self.assertEqual(self.request("/api/auth/activity", "POST", cookie=cookie)[0], 423)
        self.assertEqual(self.request("/api/auth/unlock", "POST", cookie=cookie, payload={"pin": "4321"})[0], 403)
        self.assertFalse(self.request("/api/auth/unlock", "POST", cookie=cookie, payload={"pin": "0123"})[2]["locked"])

        session_url = "/api/clients/Client%20X/sessions/1"
        session = self.request(session_url, cookie=cookie)[2]
        target = {"kind": "session", "client": "Client X", "number": 1}
        trash_url = "/api/trash?source=Clients"
        self.assertEqual(self.request(trash_url, "POST", cookie=cookie, payload=target)[0], 403)
        self.assertEqual(self.request(session_url, cookie=cookie)[0], 200)
        status, _, body = self.request(trash_url, "POST", cookie=cookie, payload={**target, "pin": "0123"})
        self.assertEqual(status, 200)
        self.assertEqual(self.request(session_url, cookie=cookie)[0], 404)
        self.assertEqual(self.request("/api/trash/undo?source=Clients", "POST", cookie=cookie,
                                      payload={"type": "clients", "token": body["token"]})[0], 200)
        self.assertEqual(self.request(session_url, cookie=cookie)[2]["content"], session["content"])

    def test_other_notes_use_the_selected_clients_source(self):
        filename = "Intake #1.md"
        primary = self.notes_root / "Clients" / "Client X" / filename
        primary.write_text("Primary notes", encoding="utf-8")
        alternate = self.notes_root / "Other clients" / "Client X" / filename
        alternate.parent.mkdir(parents=True)
        alternate.write_text("Alternate notes", encoding="utf-8")

        cookie = f"{server.SESSION_COOKIE}={self.auth.setup('coach', PASSWORD)}"
        settings = {
            "notes_root": str(self.notes_root),
            "sources": [{"path": path, "type": "clients"} for path in ("Clients", "Other clients")],
        }
        self.assertEqual(self.request("/api/settings", "PUT", payload=settings, cookie=cookie)[0], 200)

        collection = "/api/clients/Client%20X/other-notes"
        item = f"{collection}/Intake%20%231.md"
        source = "?source=Other%20clients"
        status, _, listing = self.request(collection + source, cookie=cookie)
        self.assertEqual(status, 200)
        self.assertEqual([note["filename"] for note in listing["notes"]], [filename])
        self.assertEqual(self.request(item + "?source=Disabled", cookie=cookie)[0], 404)

        status, _, note = self.request(item + source, cookie=cookie)
        self.assertEqual(status, 200)
        self.assertEqual(note["content"], "Alternate notes")
        payload = {"content": "Updated alternate notes", "etag": note["etag"]}
        status, _, updated = self.request(item + source, "PUT", payload=payload, cookie=cookie)
        self.assertEqual(status, 200)
        self.assertEqual(updated["content"], payload["content"])
        status, _, conflict = self.request(item + source, "PUT", payload=payload, cookie=cookie)
        self.assertEqual(status, 409)
        self.assertEqual(conflict["current"], updated)
        self.assertEqual(self.request(item, cookie=cookie)[2]["content"], "Primary notes")

    def test_only_one_concurrent_setup_succeeds(self):
        def create_account(username):
            try:
                return self.auth.setup(username, PASSWORD)
            except AuthError as error:
                return error.status

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(create_account, ["first", "second"]))
        self.assertEqual(results.count(409), 1)
        self.assertTrue(self.auth.authenticated(next(result for result in results if result != 409)))

    def test_failed_sign_ins_are_rate_limited_and_sessions_expire(self):
        token = self.auth.setup("coach", PASSWORD)
        with patch("app.auth.MAX_LOGIN_FAILURES", 2), patch("app.auth.time.monotonic", return_value=100):
            for _ in range(2):
                with self.assertRaises(AuthError) as error:
                    self.auth.login("coach", "incorrect")
                self.assertEqual(error.exception.status, 401)
            with self.assertRaises(AuthError) as error:
                self.auth.login("coach", PASSWORD)
            self.assertEqual(error.exception.status, 429)
        with patch("app.auth.time.monotonic", return_value=161):
            self.assertTrue(self.auth.authenticated(self.auth.login("coach", PASSWORD)))
        with patch("app.auth.time.time", return_value=10**12):
            self.assertFalse(self.auth.authenticated(token))
