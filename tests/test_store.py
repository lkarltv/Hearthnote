import tempfile
import unittest
from pathlib import Path

from app.store import Conflict, NotesStore, StoreError


class NotesStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = NotesStore(self.temporary.name)
        self.store.create_client("Test Client")

    def tearDown(self):
        self.temporary.cleanup()

    def test_create_and_update_session(self):
        session = self.store.create_session("Test Client")
        self.assertEqual(session["number"], 1)
        updated = self.store.update_session("Test Client", 1, "# Changed\n", session["etag"])
        self.assertEqual(updated["content"], "# Changed\n")

    def test_sessions_are_numbered_after_highest_existing(self):
        directory = Path(self.temporary.name) / "Test Client"
        (directory / "Session 4.md").write_text("four", encoding="utf-8")
        self.assertEqual(self.store.create_session("Test Client")["number"], 5)

    def test_stale_update_is_rejected(self):
        session = self.store.create_session("Test Client")
        self.store.update_session("Test Client", 1, "new", session["etag"])
        with self.assertRaises(Conflict):
            self.store.update_session("Test Client", 1, "stale", session["etag"])

    def test_unsafe_client_name_is_rejected(self):
        with self.assertRaises(StoreError):
            self.store.create_client("../escape")

    def test_unrelated_files_are_ignored(self):
        directory = Path(self.temporary.name) / "Test Client"
        (directory / "overview.md").write_text("ignored", encoding="utf-8")
        self.assertEqual(self.store.list_sessions("Test Client"), [])


if __name__ == "__main__":
    unittest.main()
