import io
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from app import server
from app.auth import AuthError, AuthStore
from app.store import NotesStore


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
        self.notes = NotesStore(folder / "notes")
        self.notes.create_client("Client X")
        self.notes.create_session("Client X")
        self.enterContext(patch.multiple(server, AUTH=self.auth, STORE=self.notes, SECURE_COOKIE=True))
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
        self.assertEqual(self.request(status_path)[2], {"setup_required": True, "authenticated": False})
        for method, path in [
            ("GET", "/api/clients"),
            ("GET", "/api/clients/Client%20X/sessions/1"),
            ("GET", "/api/clients/Client%20X/other-notes"),
            ("POST", "/api/clients/Client%20X/sessions"),
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
        self.assertEqual(self.request(status_path, cookie=cookie)[2], {"setup_required": False, "authenticated": True})
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
            with sqlite3.connect(reopened.path) as database:
                stored_hash, = database.execute("SELECT password_hash FROM account").fetchone()
                stored_token, = database.execute("SELECT token_hash FROM sessions").fetchone()
            self.assertEqual(len(stored_hash), 32)
            self.assertNotEqual(stored_hash, credentials["password"].encode())
            self.assertNotEqual(stored_token, cookie.split("=", 1)[1].encode())

            status, headers, _ = self.request("/api/auth/logout", "POST", cookie=cookie)
            self.assertEqual(status, 200)
            self.assertIn("Max-Age=0", headers["Set-Cookie"])
            self.assertEqual(self.request("/api/clients", cookie=cookie)[0], 401)
            self.assertEqual(self.request(status_path)[2], {"setup_required": False, "authenticated": False})
            self.assertEqual(self.request("/api/auth/login", "POST", payload={**credentials, "password": "incorrect"})[0], 401)
            status, headers, _ = self.request("/api/auth/login", "POST", payload=credentials)
            self.assertEqual(status, 200)
            self.assertNotEqual(headers["Set-Cookie"].split(";", 1)[0], cookie)

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
