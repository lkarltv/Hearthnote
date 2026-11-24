import hashlib
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from unittest.mock import patch

from app.auth import SESSION_SECONDS, AuthError, AuthStore


PASSWORD = "cedar coffee on the balcony"
PIN = "0042"
DISABLED = {"enabled": False, "ask_on_open": False, "idle_minutes": 0, "require_on_delete": False}


class PinTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_000_000
        self.enterContext(patch("app.auth.time.time", side_effect=lambda: self.now))
        self.enterContext(patch("app.auth.PASSWORD_ITERATIONS", 10))
        self.enterContext(patch("app.auth.PIN_ITERATIONS", 20))
        self.auth = AuthStore(self.enterContext(tempfile.TemporaryDirectory()))
        self.auth.initialize()

    def reopen(self):
        store = AuthStore(self.auth.directory)
        store.initialize()
        return store

    def assert_auth_error(self, status, call, *args, **kwargs):
        with self.assertRaises(AuthError) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.status, status)
        return str(caught.exception)

    @staticmethod
    def payload(**changes):
        return {"password": PASSWORD, **DISABLED, **changes}

    def test_setup_without_pin_and_unknown_sessions(self):
        self.assertEqual(
            self.auth.session_status("", opening=True),
            {"setup_required": True, "authenticated": False, "locked": False},
        )
        token = self.auth.setup("coach", PASSWORD)
        self.assertEqual(
            self.auth.session_status(token, opening=True),
            {"setup_required": False, "authenticated": True, "locked": False, "security": DISABLED},
        )
        self.auth.require_delete_pin(None)
        self.auth.logout(token)
        self.assertEqual(
            self.auth.session_status(token),
            {"setup_required": False, "authenticated": False, "locked": False},
        )
        self.assert_auth_error(401, self.auth.require_session, token)
        self.assert_auth_error(401, self.auth.unlock, token, PIN)

    def test_setup_validates_pin_and_persists_salted_hash(self):
        for invalid in ("", "042", "0" * 33, "１２３４", "123٤", " 1234", "1234\n", 1234):
            with self.subTest(invalid=invalid):
                self.assert_auth_error(400, self.auth.setup, "coach", PASSWORD, pin=invalid)
        token = self.auth.setup("coach", PASSWORD, pin=PIN)
        self.assertEqual(
            self.auth.session_status(token)["security"],
            {**DISABLED, "enabled": True, "ask_on_open": True},
        )
        with closing(sqlite3.connect(self.auth.path)) as database:
            password_salt, salt, digest, iterations = database.execute(
                "SELECT salt, pin_salt, pin_hash, pin_iterations FROM account"
            ).fetchone()
        self.assertEqual(len(salt), 16)
        self.assertNotEqual(password_salt, salt)
        self.assertEqual(digest, hashlib.pbkdf2_hmac("sha256", PIN.encode("ascii"), salt, iterations))

    def test_open_lock_persists_and_password_login_is_fallback(self):
        token = self.auth.setup("coach", PASSWORD, pin=PIN)
        self.assertFalse(self.auth.session_status(token)["locked"])
        locked = self.auth.session_status(token, opening=True)
        self.assertTrue(locked["authenticated"])
        self.assertTrue(locked["locked"])
        self.assertTrue(locked["security"]["ask_on_open"])

        reopened = self.reopen()
        self.assertEqual(reopened.session_status(token), locked)
        self.assertFalse(reopened.authenticated(token))
        self.assert_auth_error(423, reopened.require_session, token, activity=True)
        self.assert_auth_error(423, reopened.update_security, token, self.payload())
        self.assert_auth_error(403, reopened.unlock, token, "0000")

        fallback = reopened.login("coach", PASSWORD)
        self.assertNotEqual(fallback, token)
        reopened.require_session(fallback)
        self.assertTrue(reopened.session_status(token)["locked"])
        self.assertFalse(reopened.unlock(token, PIN)["locked"])
        reopened.require_session(token)
        self.assertTrue(reopened.session_status(fallback, opening=True)["locked"])
        self.assertFalse(reopened.session_status(token)["locked"])

    def test_only_activity_and_successful_unlock_restart_a_running_idle_timer(self):
        token = self.auth.setup("coach", PASSWORD, pin=PIN)
        self.auth.update_security(token, self.payload(enabled=True, idle_minutes=1))
        self.now += 59
        self.auth.require_session(token, activity=True)
        self.now += 59
        self.assertFalse(self.auth.session_status(token, opening=True)["locked"])
        self.auth.require_session(token)
        self.auth.security_settings()
        self.auth.update_security(token, self.payload(enabled=True, idle_minutes=1))
        self.now += 1
        self.assert_auth_error(423, self.auth.require_session, token, activity=True)
        self.assertTrue(self.reopen().session_status(token)["locked"])
        self.assertFalse(self.auth.unlock(token, PIN)["locked"])
        self.now += 59
        self.auth.require_session(token)
        self.now += 1
        self.assertTrue(self.auth.session_status(token)["locked"])
        self.now += SESSION_SECONDS
        self.assert_auth_error(401, self.auth.unlock, token, PIN)

    def test_enabling_idle_timeout_starts_timer_for_current_session_only(self):
        editor = self.auth.setup("coach", PASSWORD, pin=PIN)
        inactive = self.auth.login("coach", PASSWORD)
        self.now += 600
        self.auth.update_security(editor, self.payload(enabled=True, idle_minutes=1))
        self.auth.require_session(editor)
        self.assert_auth_error(423, self.auth.require_session, inactive)
        self.now += 60
        self.assert_auth_error(423, self.auth.require_session, editor)

    def test_changing_timeout_does_not_unlock_sessions_already_due(self):
        inactive = self.auth.setup("coach", PASSWORD, pin=PIN)
        self.auth.update_security(inactive, self.payload(enabled=True, idle_minutes=1))
        self.now += 60
        editor = self.auth.login("coach", PASSWORD)
        self.assertEqual(self.auth.update_security(editor, self.payload(enabled=True))["idle_minutes"], 0)
        self.assert_auth_error(423, self.auth.require_session, inactive, activity=True)
        self.auth.require_session(editor)
        self.auth.unlock(inactive, PIN)
        self.now += 600
        self.auth.require_session(inactive)

    def test_security_settings_require_password_and_replace_or_clear_pin(self):
        token = self.auth.setup("coach", PASSWORD)
        enable = self.payload(enabled=True, require_on_delete=True, new_pin=PIN, idle_minutes=1440)
        self.assert_auth_error(403, self.auth.update_security, token, {**enable, "password": "wrong"})
        self.assert_auth_error(400, self.auth.update_security, token, self.payload(enabled=True))
        for changes in ({"idle_minutes": -1}, {"idle_minutes": 1441}, {"idle_minutes": True}, {"idle_minutes": "1"},
                        {"ask_on_open": 1}, {"enabled": "yes"}, {"require_on_delete": None}):
            with self.subTest(changes=changes):
                self.assert_auth_error(400, self.auth.update_security, token, {**enable, **changes})
        self.assertEqual(self.auth.security_settings(), DISABLED)
        self.assertEqual(self.auth.update_security(token, enable), {
            **DISABLED, "enabled": True, "require_on_delete": True, "idle_minutes": 1440,
        })
        self.auth.require_delete_pin(PIN)

        replacement = "0" * 31 + "1"
        self.auth.update_security(token, {**enable, "ask_on_open": True, "new_pin": replacement})
        self.assert_auth_error(403, self.auth.require_delete_pin, PIN)
        self.auth.require_delete_pin(replacement)
        self.assertTrue(self.auth.session_status(token, opening=True)["locked"])
        editor = self.auth.login("coach", PASSWORD)
        disabled = self.auth.update_security(editor, {**enable, "enabled": False, "ask_on_open": True})
        self.assertEqual(disabled, DISABLED)
        self.assertEqual(self.reopen().security_settings(), DISABLED)
        self.assertFalse(self.auth.session_status(token, opening=True)["locked"])
        self.auth.require_delete_pin(None)
        with closing(sqlite3.connect(self.auth.path)) as database:
            self.assertEqual(database.execute("SELECT pin_salt, pin_hash, pin_iterations FROM account").fetchone(),
                             (None, None, None))

    def test_pin_attempts_are_shared_by_unlock_and_delete_across_restarts(self):
        token = self.auth.setup("coach", PASSWORD, pin=PIN)
        self.auth.update_security(token, self.payload(enabled=True, ask_on_open=True, require_on_delete=True))
        self.auth.session_status(token, opening=True)
        with patch("app.auth.MAX_PIN_FAILURES", 2):
            self.assertIn("Enter your PIN", self.assert_auth_error(403, self.auth.require_delete_pin, None))
            self.assert_auth_error(403, self.auth.unlock, token, "1000")
            reopened = self.reopen()
            self.assertIn("Incorrect PIN", self.assert_auth_error(403, reopened.require_delete_pin, "2000"))
            self.assert_auth_error(429, reopened.unlock, token, PIN)
            self.assert_auth_error(429, self.auth.require_delete_pin, PIN)
            self.now += 60
            self.assertFalse(reopened.unlock(token, PIN)["locked"])
            self.auth.require_delete_pin(PIN)

    def test_concurrent_pin_verification_cannot_bypass_rate_limit(self):
        token = self.auth.setup("coach", PASSWORD, pin=PIN)
        self.auth.update_security(token, self.payload(enabled=True, require_on_delete=True))
        reopened = self.reopen()

        def verify(index):
            try:
                if index % 2:
                    self.auth.unlock(token, "1000")
                else:
                    reopened.require_delete_pin("2000")
            except AuthError as error:
                return error.status

        with patch("app.auth.MAX_PIN_FAILURES", 2), ThreadPoolExecutor(max_workers=4) as executor:
            self.assertCountEqual(executor.map(verify, range(4)), (403, 403, 429, 429))

    def test_initializer_migrates_existing_account_and_sessions(self):
        legacy = AuthStore(self.enterContext(tempfile.TemporaryDirectory()))
        token = "A" * 43
        salt = b"legacy salt"
        with closing(sqlite3.connect(legacy.path)) as database, database:
            database.executescript("""
                CREATE TABLE account (id INTEGER PRIMARY KEY CHECK (id = 1), username TEXT NOT NULL,
                    salt BLOB NOT NULL, password_hash BLOB NOT NULL, iterations INTEGER NOT NULL);
                CREATE TABLE sessions (token_hash BLOB PRIMARY KEY, expires_at INTEGER NOT NULL);
            """)
            database.execute("INSERT INTO account VALUES (1, 'coach', ?, ?, 10)", (
                salt, hashlib.pbkdf2_hmac("sha256", PASSWORD.encode(), salt, 10),
            ))
            database.execute("INSERT INTO sessions VALUES (?, ?)", (
                hashlib.sha256(token.encode()).digest(), self.now + SESSION_SECONDS,
            ))
        legacy.initialize()
        self.assertEqual(legacy.session_status(token, opening=True)["security"], DISABLED)
        legacy.require_session(legacy.login("coach", PASSWORD))
        legacy.update_security(token, self.payload(enabled=True, new_pin=PIN, idle_minutes=1))
        legacy.require_session(token)
        self.now += 60
        legacy.initialize()
        self.assert_auth_error(423, legacy.require_session, token)
        legacy.unlock(token, PIN)
