import json
import tempfile
import unittest
from pathlib import Path

from app.config import VaultManager
from app.store import StoreError


class VaultManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.demo = self.base / "demo"
        self.demo.mkdir()
        self.config = self.base / "config" / "settings.json"

    def tearDown(self):
        self.temporary.cleanup()

    def test_update_persists_selected_folder(self):
        selected = self.base / "selected"
        selected.mkdir()
        manager = VaultManager(self.demo, self.config)
        details = manager.update(str(selected))
        self.assertEqual(details["notes_root"], str(selected))
        self.assertEqual(
            json.loads(self.config.read_text(encoding="utf-8"))["notes_root"],
            str(selected),
        )
        reloaded = VaultManager(self.demo, self.config)
        self.assertEqual(reloaded.store.root, selected)

    def test_vault_root_resolves_coaching_notes_child(self):
        vault = self.base / "Obsidian Vault"
        notes = vault / "Coaching notes"
        notes.mkdir(parents=True)
        manager = VaultManager(self.demo, self.config)
        details = manager.update(str(vault))
        self.assertEqual(details["notes_root"], str(notes))

    def test_typed_folders_persist_and_can_be_removed(self):
        coaching = self.base / "Coaching"
        clients = coaching / "Clients"
        career = coaching / "Educational materials" / "Career"
        clients.mkdir(parents=True)
        career.mkdir(parents=True)
        manager = VaultManager(coaching, self.config)
        self.assertEqual(manager.store.root, clients)
        self.assertEqual(manager.browse(str(self.base), "Educational materials")["folders"], [
            {"path": "Educational materials/Career", "name": "Career"},
        ])
        selected = [{"path": "Educational materials/Career", "type": "knowledge"}]
        manager.update(str(coaching), selected)
        reloaded = VaultManager(coaching, self.config)
        self.assertEqual(reloaded.source_folder("knowledge", selected[0]["path"]), career)
        with self.assertRaises(StoreError):
            reloaded.client_store()
        reloaded.update(str(coaching), [])
        self.assertEqual(VaultManager(coaching, self.config).details()["sources"], [])
        self.assertTrue(career.is_dir())

    def test_invalid_folder_selection_leaves_settings_unchanged(self):
        manager = VaultManager(self.demo, self.config, boundary=str(self.demo))
        (self.demo / "linked").symlink_to(self.base, target_is_directory=True)
        for path in ("../config", "/tmp", "linked"):
            with self.subTest(path=path), self.assertRaises(StoreError):
                manager.update(str(self.demo), [{"path": path, "type": "knowledge"}])
        with self.assertRaises(StoreError):
            manager.browse(str(self.base))
        self.assertEqual(manager.store.root, self.demo)
        self.assertFalse(self.config.exists())

    def test_missing_folder_is_rejected(self):
        manager = VaultManager(self.demo, self.config)
        with self.assertRaises(StoreError):
            manager.update(str(self.base / "missing"))

    def test_relative_folder_is_rejected(self):
        manager = VaultManager(self.demo, self.config)
        with self.assertRaises(StoreError):
            manager.update("relative/path")


if __name__ == "__main__":
    unittest.main()
