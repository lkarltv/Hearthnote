import tempfile
import unittest
from pathlib import Path

from app.store import Conflict, NotFound, NotesStore, StoreError


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

    def test_other_markdown_files_are_excluded_from_sessions(self):
        directory = Path(self.temporary.name) / "Test Client"
        (directory / "overview.md").write_text("ignored", encoding="utf-8")
        self.assertEqual(self.store.list_sessions("Test Client"), [])

    def test_other_notes_use_the_existing_session_pattern(self):
        directory = Path(self.temporary.name) / "Test Client"
        filenames = ["Session 4.md", "session1.md", "Session 01.md", "Introducción #1.MD", "Other.txt"]
        for filename in filenames:
            (directory / filename).write_text(filename, encoding="utf-8")
        (directory / "Archive.md").mkdir()
        (directory / "Archive.md" / "Nested.md").write_text("nested", encoding="utf-8")

        notes = self.store.list_other_notes("Test Client")
        self.assertEqual([note["filename"] for note in notes], ["Introducción #1.MD", "Session 01.md", "session1.md"])
        self.assertEqual(self.store.read_other_note("Test Client", "Introducción #1.MD")["content"], "Introducción #1.MD")
        self.assertEqual(self.store.create_session("Test Client")["number"], 5)

    def test_other_notes_reject_sessions_and_paths_outside_client_folder(self):
        directory = Path(self.temporary.name) / "Test Client"
        outside = directory.parent / "Outside.md"
        outside.write_text("outside", encoding="utf-8")
        (directory / "Link.md").symlink_to(outside)
        self.store.create_session("Test Client")

        self.assertEqual(self.store.list_other_notes("Test Client"), [])
        for filename in ["Session 1.md", "../Outside.md", "Link.md", str(outside)]:
            with self.subTest(filename=filename), self.assertRaises(NotFound):
                self.store.read_other_note("Test Client", filename)

    def test_other_note_saves_markdown_to_original_filename_and_checks_conflicts(self):
        filename = "Intake #1?.md"
        path = Path(self.temporary.name) / "Test Client" / filename
        path.write_text("# Intake\n", encoding="utf-8")
        note = self.store.read_other_note("Test Client", filename)

        content = "# Intake\n\n- **Discuss next time**\n"
        saved = self.store.update_other_note("Test Client", filename, content, note["etag"])
        self.assertEqual(path.read_text(encoding="utf-8"), content)
        self.assertEqual(saved["filename"], filename)
        self.assertNotEqual(saved["etag"], note["etag"])

        path.write_text("# Edited externally\n", encoding="utf-8")
        with self.assertRaises(Conflict) as error:
            self.store.update_other_note("Test Client", filename, "Stale", saved["etag"])
        self.assertEqual(error.exception.current["content"], "# Edited externally\n")
        self.assertEqual(path.read_text(encoding="utf-8"), "# Edited externally\n")

    def test_update_other_note_does_not_create_files_or_reclassify_sessions(self):
        self.store.create_session("Test Client")
        for filename in ("Missing.md", "Session 1.md", "../Outside.md"):
            with self.subTest(filename=filename), self.assertRaises(NotFound):
                self.store.update_other_note("Test Client", filename, "unexpected", "unused")


if __name__ == "__main__":
    unittest.main()
