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
PIN_ITERATIONS = 600_000
PIN_RE = re.compile(r"[0-9]{4,32}")
SESSION_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{43}")
LOGIN_WINDOW_SECONDS = 60
MAX_LOGIN_FAILURES = 8
PIN_WINDOW_SECONDS = 60
MAX_PIN_FAILURES = 8


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
    def _connect(self, *, write=False):
        with closing(sqlite3.connect(self.path)) as database, database:
            database.row_factory = sqlite3.Row
            if write:
                # Keep policy and session checks in the same transaction as their updates.
                database.execute("BEGIN IMMEDIATE")
            yield database

    def initialize(self) -> None:
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        with self._connect(write=True) as database:
            database.execute("""
                CREATE TABLE IF NOT EXISTS account (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    username TEXT NOT NULL,
                    salt BLOB NOT NULL,
                    password_hash BLOB NOT NULL,
                    iterations INTEGER NOT NULL
                )
            """)
            database.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash BLOB PRIMARY KEY,
                    expires_at INTEGER NOT NULL
                )
            """)
            if database.execute("PRAGMA user_version").fetchone()[0] == 0:
                for statement in (
                    "ALTER TABLE account ADD COLUMN pin_salt BLOB",
                    "ALTER TABLE account ADD COLUMN pin_hash BLOB",
                    "ALTER TABLE account ADD COLUMN pin_iterations INTEGER",
                    "ALTER TABLE account ADD COLUMN ask_on_open INTEGER NOT NULL DEFAULT 0",
                    "ALTER TABLE account ADD COLUMN idle_minutes INTEGER NOT NULL DEFAULT 0",
                    "ALTER TABLE account ADD COLUMN require_on_delete INTEGER NOT NULL DEFAULT 0",
                    "ALTER TABLE sessions ADD COLUMN last_activity INTEGER NOT NULL DEFAULT 0",
                    "ALTER TABLE sessions ADD COLUMN locked INTEGER NOT NULL DEFAULT 0",
                    "CREATE TABLE pin_failures (attempted_at INTEGER NOT NULL)",
                ):
                    database.execute(statement)
                database.execute("UPDATE sessions SET last_activity = ?", (int(time.time()),))
                database.execute("PRAGMA user_version = 1")

    @staticmethod
    def _password_hash(password: str, salt: bytes, iterations: int) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)

    @classmethod
    def _pin_credentials(cls, pin: str) -> tuple[bytes, bytes, int]:
        if not isinstance(pin, str) or not PIN_RE.fullmatch(pin):
            raise AuthError("Use a PIN of 4 to 32 digits (0–9).")
        salt = secrets.token_bytes(16)
        return salt, cls._password_hash(pin, salt, PIN_ITERATIONS), PIN_ITERATIONS

    @classmethod
    def _credentials(cls, username, password) -> tuple[str, str]:
        if not isinstance(username, str) or not isinstance(password, str):
            raise AuthError("Enter a username and password.")
        username = normalize("NFC", username.strip())
        if not username or len(username) > 80 or not username.isprintable():
            raise AuthError("Use a username between 1 and 80 characters.")
        return username, cls._normalized_password(password)

    @staticmethod
    def _normalized_password(password) -> str:
        if not isinstance(password, str):
            raise AuthError("Enter a password.")
        password = normalize("NFC", password)
        if not password or len(password) > 256:
            raise AuthError("Enter a password of up to 256 characters.")
        try:
            password.encode("utf-8")
        except UnicodeEncodeError:
            raise AuthError("The password contains an invalid character.") from None
        return password

    @staticmethod
    def _token_hash(token: str) -> bytes:
        return hashlib.sha256(token.encode("ascii")).digest()

    def _create_session(self, database: sqlite3.Connection) -> str:
        now = int(time.time())
        token = secrets.token_urlsafe(32)
        database.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        database.execute(
            "INSERT INTO sessions (token_hash, expires_at, last_activity) VALUES (?, ?, ?)",
            (self._token_hash(token), now + SESSION_SECONDS, now),
        )
        return token

    def setup_required(self) -> bool:
        with self._connect() as database:
            return database.execute("SELECT 1 FROM account WHERE id = 1").fetchone() is None

    def setup(self, username, password, pin=None) -> str:
        if not self.setup_required():
            raise AuthError("Hearthnote already has an account. Sign in instead.", 409)
        username, password = self._credentials(username, password)
        if len(password) < 8:
            raise AuthError("Use at least 8 characters for your password.")
        salt = secrets.token_bytes(16)
        password_hash = self._password_hash(password, salt, PASSWORD_ITERATIONS)
        pin_credentials = (None, None, None) if pin is None else self._pin_credentials(pin)
        with self._connect() as database:
            result = database.execute(
                """INSERT OR IGNORE INTO account
                   (id, username, salt, password_hash, iterations, pin_salt, pin_hash, pin_iterations, ask_on_open)
                   VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (username, salt, password_hash, PASSWORD_ITERATIONS, *pin_credentials, pin is not None),
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
        if not isinstance(token, str) or not SESSION_TOKEN_RE.fullmatch(token):
            return False
        status = self.session_status(token)
        return status["authenticated"] and not status["locked"]

    @staticmethod
    def _settings(row: sqlite3.Row | None) -> dict:
        enabled = row is not None and bool(row["enabled"])
        return {
            "enabled": enabled,
            "ask_on_open": enabled and bool(row["ask_on_open"]),
            "idle_minutes": row["idle_minutes"] if enabled else 0,
            "require_on_delete": enabled and bool(row["require_on_delete"]),
        }

    def security_settings(self) -> dict:
        with self._connect() as database:
            return self._settings(database.execute("""
                SELECT pin_hash IS NOT NULL AS enabled, ask_on_open, idle_minutes, require_on_delete
                FROM account WHERE id = 1
            """).fetchone())

    def _session(
        self, database: sqlite3.Connection, token: str, now: int, *, opening=False, persist_lock=True,
    ) -> sqlite3.Row | None:
        if not isinstance(token, str) or not SESSION_TOKEN_RE.fullmatch(token):
            return None
        token_hash = self._token_hash(token)
        session = database.execute("""
            SELECT token_hash, sessions.locked AS was_locked,
                   sessions.locked OR (pin_hash IS NOT NULL AND (
                       (? AND ask_on_open) OR (idle_minutes > 0 AND last_activity <= ? - 60 * idle_minutes)
                   )) AS locked,
                   pin_hash IS NOT NULL AS enabled, ask_on_open, idle_minutes, require_on_delete
            FROM sessions CROSS JOIN account
            WHERE token_hash = ? AND expires_at > ? AND account.id = 1
        """, (opening, now, token_hash, now)).fetchone()
        if persist_lock and session is not None and session["locked"] and not session["was_locked"]:
            database.execute("UPDATE sessions SET locked = 1 WHERE token_hash = ?", (token_hash,))
        return session

    def _status(self, database: sqlite3.Connection, session: sqlite3.Row | None, *, unlocked=False) -> dict:
        if session is None:
            return {
                "setup_required": database.execute("SELECT 1 FROM account WHERE id = 1").fetchone() is None,
                "authenticated": False,
                "locked": False,
            }
        return {
            "setup_required": False,
            "authenticated": True,
            "locked": not unlocked and bool(session["locked"]),
            "security": self._settings(session),
        }

    def session_status(self, token: str, *, opening=False) -> dict:
        with self._connect(write=opening) as database:
            session = self._session(database, token, int(time.time()), opening=opening, persist_lock=opening)
            return self._status(database, session)

    @staticmethod
    def _session_error(session: sqlite3.Row | None) -> AuthError | None:
        if session is None:
            return AuthError("Sign in to access Hearthnote.", 401)
        if session["locked"]:
            return AuthError("Hearthnote is locked. Enter your PIN or sign in with your password.", 423)
        return None

    def require_session(self, token: str, *, activity=False) -> None:
        with self._connect(write=True) as database:
            now = int(time.time())
            session = self._session(database, token, now)
            error = self._session_error(session)
            if error is None and activity:
                database.execute(
                    "UPDATE sessions SET last_activity = ? WHERE token_hash = ?",
                    (now, session["token_hash"]),
                )
        if error is not None:
            raise error

    def update_security(self, token: str, payload: dict) -> dict:
        with self._connect(write=True) as database:
            now = int(time.time())
            session = self._session(database, token, now)
            error = self._session_error(session)
            if error is None:
                return self._save_security(database, session, payload)
        raise error

    def _save_security(self, database: sqlite3.Connection, session: sqlite3.Row, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise AuthError("Enter the PIN settings and your current account password.")
        salt, password_hash, iterations, pin_salt, pin_hash, pin_iterations = database.execute("""
            SELECT salt, password_hash, iterations, pin_salt, pin_hash, pin_iterations FROM account WHERE id = 1
        """).fetchone()
        try:
            password = self._normalized_password(payload.get("password"))
        except AuthError:
            raise AuthError("Enter your current account password.", 403) from None
        if not secrets.compare_digest(self._password_hash(password, salt, iterations), password_hash):
            raise AuthError("Incorrect account password.", 403)

        enabled, ask_on_open, require_on_delete = (
            payload.get(field) for field in ("enabled", "ask_on_open", "require_on_delete")
        )
        if any(type(value) is not bool for value in (enabled, ask_on_open, require_on_delete)):
            raise AuthError("Choose whether to enable each PIN setting.")
        idle_minutes = payload.get("idle_minutes")
        if type(idle_minutes) is not int or not 0 <= idle_minutes <= 1440:
            raise AuthError("Enter an idle timeout from 0 to 1440 minutes.")

        new_pin = payload.get("new_pin")
        if not enabled:
            pin_salt = pin_hash = pin_iterations = None
            ask_on_open = require_on_delete = False
            idle_minutes = 0
            database.execute("UPDATE sessions SET locked = 0 WHERE locked")
        else:
            if new_pin is not None or pin_hash is None:
                pin_salt, pin_hash, pin_iterations = self._pin_credentials(new_pin)
            old_idle_minutes = session["idle_minutes"]
            if idle_minutes and not old_idle_minutes:
                database.execute(
                    "UPDATE sessions SET last_activity = ? WHERE token_hash = ?",
                    (int(time.time()), session["token_hash"]),
                )
            elif old_idle_minutes and idle_minutes != old_idle_minutes:
                # A timeout that already elapsed must remain locked under the new policy.
                now = int(time.time())
                database.execute("""
                    UPDATE sessions SET locked = 1
                    WHERE NOT locked AND expires_at > ? AND last_activity <= ?
                """, (now, now - 60 * old_idle_minutes))
        database.execute("""
            UPDATE account SET pin_salt = ?, pin_hash = ?, pin_iterations = ?,
                ask_on_open = ?, idle_minutes = ?, require_on_delete = ? WHERE id = 1
        """, (pin_salt, pin_hash, pin_iterations, ask_on_open, idle_minutes, require_on_delete))
        if not enabled or new_pin is not None:
            database.execute("DELETE FROM pin_failures")
        return {
            "enabled": enabled,
            "ask_on_open": ask_on_open,
            "idle_minutes": idle_minutes,
            "require_on_delete": require_on_delete,
        }

    def _verify_pin(self, database: sqlite3.Connection, pin, now: int) -> AuthError | None:
        if pin is None or pin == "":
            return AuthError("Enter your PIN.", 403)
        database.execute("DELETE FROM pin_failures WHERE attempted_at <= ?", (now - PIN_WINDOW_SECONDS,))
        if database.execute("SELECT COUNT(*) FROM pin_failures").fetchone()[0] >= MAX_PIN_FAILURES:
            return AuthError("Too many PIN attempts. Try again in a minute.", 429)
        salt, pin_hash, iterations = database.execute("""
            SELECT pin_salt, pin_hash, pin_iterations FROM account WHERE id = 1
        """).fetchone()
        if (
            not isinstance(pin, str) or not PIN_RE.fullmatch(pin)
            or not secrets.compare_digest(self._password_hash(pin, salt, iterations), pin_hash)
        ):
            database.execute("INSERT INTO pin_failures (attempted_at) VALUES (?)", (now,))
            return AuthError("Incorrect PIN.", 403)
        database.execute("DELETE FROM pin_failures")
        return None

    def unlock(self, token: str, pin) -> dict:
        with self._connect(write=True) as database:
            now = int(time.time())
            session = self._session(database, token, now)
            if session is None:
                raise self._session_error(session)
            error = self._verify_pin(database, pin, now) if session["enabled"] else None
            if error is None:
                if session["enabled"]:
                    database.execute(
                        "UPDATE sessions SET locked = 0, last_activity = ? WHERE token_hash = ?",
                        (now, session["token_hash"]),
                    )
                return self._status(database, session, unlocked=True)
        raise error

    def require_delete_pin(self, pin) -> None:
        with self._connect(write=True) as database:
            required = database.execute("""
                SELECT 1 FROM account WHERE id = 1 AND pin_hash IS NOT NULL AND require_on_delete
            """).fetchone()
            error = self._verify_pin(database, pin, int(time.time())) if required else None
        if error is not None:
            raise error

    def logout(self, token: str) -> None:
        if isinstance(token, str) and SESSION_TOKEN_RE.fullmatch(token):
            with self._connect() as database:
                database.execute("DELETE FROM sessions WHERE token_hash = ?", (self._token_hash(token),))
