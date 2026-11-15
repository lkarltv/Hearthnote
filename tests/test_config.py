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
