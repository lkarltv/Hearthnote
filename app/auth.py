from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
import time
from collections import deque
from contextlib import closing, contextmanager
from pathlib import Path
from threading import Lock
from unicodedata import normalize


SESSION_SECONDS = 7 * 24 * 60 * 60
PASSWORD_ITERATIONS = 600_000
SESSION_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{43}")
LOGIN_WINDOW_SECONDS = 60
MAX_LOGIN_FAILURES = 8


class AuthError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class AuthStore:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory).expanduser()
        self.path = self.directory / "auth.sqlite3"
        self._login_lock = Lock()
        self._login_failures = deque()

    @contextmanager
    def _connect(self):
        with closing(sqlite3.connect(self.path)) as database, database:
            yield database

    def initialize(self) -> None:
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        with self._connect() as database:
            database.executescript("""
                CREATE TABLE IF NOT EXISTS account (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    username TEXT NOT NULL,
                    salt BLOB NOT NULL,
                    password_hash BLOB NOT NULL,
                    iterations INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash BLOB PRIMARY KEY,
                    expires_at INTEGER NOT NULL
                );
            """)

    @staticmethod
    def _password_hash(password: str, salt: bytes, iterations: int) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)

    @staticmethod
    def _credentials(username, password) -> tuple[str, str]:
        if not isinstance(username, str) or not isinstance(password, str):
            raise AuthError("Enter a username and password.")
        username = normalize("NFC", username.strip())
        password = normalize("NFC", password)
        if not username or len(username) > 80 or not username.isprintable():
            raise AuthError("Use a username between 1 and 80 characters.")
        if not password or len(password) > 256:
            raise AuthError("Enter a password of up to 256 characters.")
        try:
            password.encode("utf-8")
        except UnicodeEncodeError:
            raise AuthError("The password contains an invalid character.") from None
        return username, password

    @staticmethod
    def _token_hash(token: str) -> bytes:
        return hashlib.sha256(token.encode("ascii")).digest()

    def _create_session(self, database: sqlite3.Connection) -> str:
        now = int(time.time())
        token = secrets.token_urlsafe(32)
        database.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        database.execute(
            "INSERT INTO sessions (token_hash, expires_at) VALUES (?, ?)",
            (self._token_hash(token), now + SESSION_SECONDS),
        )
        return token

    def setup_required(self) -> bool:
        with self._connect() as database:
            return database.execute("SELECT 1 FROM account WHERE id = 1").fetchone() is None

    def setup(self, username, password) -> str:
        if not self.setup_required():
            raise AuthError("Hearthnote already has an account. Sign in instead.", 409)
        username, password = self._credentials(username, password)
        if len(password) < 8:
            raise AuthError("Use at least 8 characters for your password.")
        salt = secrets.token_bytes(16)
        password_hash = self._password_hash(password, salt, PASSWORD_ITERATIONS)
        with self._connect() as database:
            result = database.execute(
                "INSERT OR IGNORE INTO account VALUES (1, ?, ?, ?, ?)",
                (username, salt, password_hash, PASSWORD_ITERATIONS),
            )
            if not result.rowcount:
                raise AuthError("Hearthnote already has an account. Sign in instead.", 409)
            return self._create_session(database)

    def login(self, username, password) -> str:
        username, password = self._credentials(username, password)
        with self._login_lock, self._connect() as database:
            now = time.monotonic()
            while self._login_failures and now - self._login_failures[0] >= LOGIN_WINDOW_SECONDS:
                self._login_failures.popleft()
            if len(self._login_failures) >= MAX_LOGIN_FAILURES:
                raise AuthError("Too many sign-in attempts. Try again in a minute.", 429)
            account = database.execute(
                "SELECT username, salt, password_hash, iterations FROM account WHERE id = 1"
            ).fetchone()
            if account is None:
                raise AuthError("Set up your Hearthnote account first.", 409)
            stored_username, salt, password_hash, iterations = account
            password_matches = secrets.compare_digest(self._password_hash(password, salt, iterations), password_hash)
            if not password_matches or username != stored_username:
                self._login_failures.append(now)
                raise AuthError("Incorrect username or password.", 401)
            self._login_failures.clear()
            return self._create_session(database)

    def authenticated(self, token: str) -> bool:
        if not SESSION_TOKEN_RE.fullmatch(token):
            return False
        with self._connect() as database:
            return database.execute(
                "SELECT 1 FROM sessions WHERE token_hash = ? AND expires_at > ?",
                (self._token_hash(token), int(time.time())),
            ).fetchone() is not None

    def logout(self, token: str) -> None:
        if SESSION_TOKEN_RE.fullmatch(token):
            with self._connect() as database:
                database.execute("DELETE FROM sessions WHERE token_hash = ?", (self._token_hash(token),))
