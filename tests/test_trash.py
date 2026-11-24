import json
import tempfile
import unittest
from pathlib import Path

from app import trash
from app.config import VaultManager
from app.knowledge import list_topics
from app.store import Conflict, NotFound, StoreError


class TrashTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "vault"
        self.clients = self.root / "Clients"
        self.client = self.clients / "Test Client"
        self.client.mkdir(parents=True)
        self.knowledge = self.root / "Educational materials"
        self.topic = self.knowledge / "Parent" / "Topic"
        self.topic.mkdir(parents=True)
        self.config = self.base / "settings.json"
        self.vault = VaultManager(self.root, self.config)

    def move(self, source, kind, **payload):
        return trash.move(self.vault, source, {"kind": kind, **payload})["token"]

    def restore(self, token, *, source="Clients", source_type="clients"):
        return trash.restore(self.vault, source, {"type": source_type, "token": token})

    def other_note(self, filename="Intake #1.md"):
        path = self.client / filename
        path.write_text("# Intake\n", encoding="utf-8")
        return path

    def test_undo_session_preserves_legacy_filename_across_restart(self):
        session = self.client / "session4.MD"
        session.write_bytes(b"# Original\r\n")
        token = self.move("Clients", "session", client=self.client.name, number=4)
        self.assertFalse(session.exists())
        self.assertEqual(self.vault.store.list_sessions(self.client.name), [])

        self.vault = VaultManager(self.root, self.config)
        self.assertEqual(self.restore(token), {"restored": True})
        self.assertEqual(session.read_bytes(), b"# Original\r\n")
        with self.assertRaises(NotFound):
            self.restore(token)

    def test_numbered_session_move_uses_canonical_filename(self):
        preferred = self.client / "Session 1.md"
        preferred.write_text("preferred", encoding="utf-8")
        fallback = self.client / "Session1.md"
        fallback.write_text("fallback", encoding="utf-8")
        self.move("Clients", "session", client=self.client.name, number=1)
        self.assertFalse(preferred.exists())
        self.assertEqual(fallback.read_text(encoding="utf-8"), "fallback")

    def test_restore_session_conflicts_with_recreated_session_number(self):
        original = self.client / "session1.md"
        original.write_text("original", encoding="utf-8")
        token = self.move("Clients", "session", client=self.client.name, number=1)
        self.vault.store.create_session(self.client.name)
        recreated = self.client / "Session 1.md"
        with self.assertRaises(Conflict):
            self.restore(token)
        self.assertTrue(recreated.exists())
        self.assertFalse(original.exists())
        recreated.unlink()
        self.restore(token)
        self.assertEqual(original.read_text(encoding="utf-8"), "original")

    def test_other_note_collision_preserves_both_versions_and_token(self):
        note = self.other_note()
        token = self.move("Clients", "other-note", client=self.client.name, filename=note.name)
        self.assertEqual(self.vault.store.list_other_notes(self.client.name), [])
        note.write_text("new", encoding="utf-8")
        with self.assertRaises(Conflict):
            self.restore(token)
        self.assertEqual(note.read_text(encoding="utf-8"), "new")
        note.unlink()
        self.restore(token)
        self.assertEqual(note.read_text(encoding="utf-8"), "# Intake\n")

    def test_client_folder_undo_preserves_contents_without_overwriting_new_folder(self):
        (self.client / ".archive").mkdir()
        attachment = self.client / ".archive" / "attachment.bin"
        attachment.write_bytes(b"\x00\xff")
        token = self.move("Clients", "client", client=self.client.name)
        self.assertEqual(self.vault.store.list_clients(), [])
        self.client.mkdir()
        with self.assertRaises(Conflict):
            self.restore(token)
        self.assertEqual(list(self.client.iterdir()), [])
        self.client.rmdir()
        self.restore(token)
        self.assertEqual(attachment.read_bytes(), b"\x00\xff")

    def test_knowledge_material_and_topic_are_independently_recoverable(self):
        material = self.topic / "Handout.MD"
        material.write_text("# Knowledge", encoding="utf-8")
        attachment = self.topic / "Figure.bin"
        attachment.write_bytes(b"\x01")
        source = self.knowledge.name
        material_token = self.move(source, "material", path="Parent/Topic/Handout.MD")
        self.assertEqual(list_topics(self.knowledge), [])
        folder_token = self.move(source, "topic", path="Parent/Topic")
        with self.assertRaises(NotFound):
            self.restore(material_token, source=source, source_type="knowledge")
        self.restore(folder_token, source=source, source_type="knowledge")
        self.restore(material_token, source=source, source_type="knowledge")
        self.assertEqual(attachment.read_bytes(), b"\x01")
        self.assertEqual(list_topics(self.knowledge)[0]["materials"][0]["path"], "Parent/Topic/Handout.MD")

    def test_tokens_are_scoped_to_configured_source_and_type(self):
        (self.root / "Second").mkdir()
        self.vault.update(str(self.root), [
            {"path": "Clients", "type": "clients"}, {"path": "Second", "type": "clients"},
        ])
        token = self.move("Clients", "client", client=self.client.name)
        with self.assertRaises(NotFound):
            self.restore(token, source="Second")
        self.vault.update(str(self.root), [{"path": "Clients", "type": "knowledge"}])
        with self.assertRaises(NotFound):
            self.restore(token, source_type="knowledge")
        self.assertFalse(self.client.exists())
        self.vault.update(str(self.root), [{"path": "Clients", "type": "clients"}])
        self.restore(token)

    def test_cannot_delete_another_source_or_its_ancestor_or_content(self):
        material = self.topic / "Handout.md"
        material.write_text("source contents", encoding="utf-8")
        nested = material.parent.relative_to(self.root).as_posix()
        self.vault.update(str(self.root), [
            {"path": self.knowledge.name, "type": "knowledge"}, {"path": nested, "type": "knowledge"},
        ])
        for kind, path in (("topic", "."), ("topic", "Parent"), ("topic", "Parent/Topic"),
                           ("material", "Parent/Topic/Handout.md")):
            with self.subTest(kind=kind, path=path), self.assertRaises(StoreError):
                self.move(self.knowledge.name, kind, path=path)
        self.assertEqual(material.read_text(encoding="utf-8"), "source contents")
        token = self.move(nested, "material", path="Handout.md")
        self.restore(token, source=nested, source_type="knowledge")

    def test_client_folder_cannot_contain_another_source(self):
        nested = self.client / "Resources"
        nested.mkdir()
        self.vault.update(str(self.root), [
            {"path": "Clients", "type": "clients"},
            {"path": nested.relative_to(self.root).as_posix(), "type": "knowledge"},
        ])
        with self.assertRaises(StoreError):
            self.move("Clients", "client", client=self.client.name)
        note = self.other_note()
        token = self.move("Clients", "other-note", client=self.client.name, filename=note.name)
        self.restore(token)
        self.assertTrue(nested.is_dir())

    def test_restore_rechecks_newly_configured_nested_source_boundary(self):
        material = self.topic / "Handout.md"
        material.touch()
        token = self.move(self.knowledge.name, "material", path="Parent/Topic/Handout.md")
        self.vault.update(str(self.root), [
            {"path": self.knowledge.name, "type": "knowledge"},
            {"path": self.topic.relative_to(self.root).as_posix(), "type": "knowledge"},
        ])
        with self.assertRaises(StoreError):
            self.restore(token, source=self.knowledge.name, source_type="knowledge")
        self.assertFalse(material.exists())

    def test_malformed_and_hidden_targets_are_rejected(self):
        hidden = self.other_note(".hidden.md")
        session = self.other_note("Session 1.md")
        source = self.knowledge.name
        for path in ("", ".", "../Clients", "/Parent", "Parent//Topic", "Parent/./Topic", ".hidden/x", "a\\b", "a\x00b", [], "a" * 10_000):
            with self.subTest(path=str(path)[:50]), self.assertRaises(StoreError):
                self.move(source, "topic", path=path)
        for name in (".hidden.md", "Session 1.md", "../escape.md", "Parent\\escape.md", {}):
            with self.subTest(name=name), self.assertRaises(StoreError):
                self.move("Clients", "other-note", client=self.client.name, filename=name)
        for number in (True, -1, 0, "1", {}):
            with self.subTest(number=number), self.assertRaises(StoreError):
                self.move("Clients", "session", client=self.client.name, number=number)
        self.assertTrue(hidden.exists())
        self.assertTrue(session.exists())
        self.assertFalse((self.clients / trash.TRASH_DIR).exists())

    def test_symlinks_are_not_followed_in_move_or_restore(self):
        material = self.topic / "Handout.md"
        material.touch()
        alias = self.knowledge / "Alias"
        alias.symlink_to(self.topic, target_is_directory=True)
        link = self.knowledge / "Handout.md"
        link.symlink_to(material)
        client_alias = self.clients / "Alias"
        client_alias.symlink_to(self.client, target_is_directory=True)
        for path in ("Alias/Handout.md", "Handout.md"):
            with self.assertRaises(StoreError):
                self.move(self.knowledge.name, "material", path=path)
        with self.assertRaises(StoreError):
            self.move("Clients", "client", client=client_alias.name)

        token = self.move(self.knowledge.name, "material", path="Parent/Topic/Handout.md")
        self.topic.rmdir()
        outside = self.base / "outside"
        outside.mkdir()
        self.topic.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(StoreError):
            self.restore(token, source=self.knowledge.name, source_type="knowledge")
        self.assertEqual(list(outside.iterdir()), [])

    def test_reserved_trash_path_cannot_be_redirected(self):
        note = self.other_note()
        outside = self.base / "outside"
        outside.mkdir()
        (self.clients / trash.TRASH_DIR).symlink_to(outside, target_is_directory=True)
        with self.assertRaises(StoreError):
            self.move("Clients", "other-note", client=self.client.name, filename=note.name)
        self.assertTrue(note.exists())
        self.assertEqual(list(outside.iterdir()), [])

    def test_invalid_restore_tokens_and_records_cannot_escape_source(self):
        note = self.other_note()
        token = self.move("Clients", "other-note", client=self.client.name, filename=note.name)
        entry = self.clients / trash.TRASH_DIR / token
        record = entry / "entry.json"
        for invalid in ("../" + token, "/" + token, token + "\x00", {}):
            with self.subTest(token=invalid), self.assertRaises(StoreError):
                self.restore(invalid)
        for path in ("../escape.md", self.client.name + "/.hidden.md", self.client.name + "/Session 1.md"):
            record.write_text(json.dumps({"kind": "other-note", "path": path}), encoding="utf-8")
            with self.subTest(path=path), self.assertRaises(StoreError):
                self.restore(token)
        self.assertTrue((entry / "item").is_file())
        self.assertFalse(note.exists())


if __name__ == "__main__":
    unittest.main()
