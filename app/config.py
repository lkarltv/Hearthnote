from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from .store import NotesStore, StoreError


class VaultManager:
    """Owns the active notes store and persists a user-selected root folder."""

    def __init__(self, default_root: str | Path, config_path: str | Path):
        self.config_path = Path(config_path).expanduser().resolve()
        self._lock = threading.RLock()
        configured_root = self._read_config() or str(default_root)
        try:
            self._store = self._validated_store(configured_root)
        except StoreError:
            # A removed drive should not prevent the app from starting. The configured
            # path remains visible in settings so the user can correct it.
            self._store = NotesStore(default_root)

    @property
    def store(self) -> NotesStore:
        with self._lock:
            return self._store

    def details(self) -> dict:
        store = self.store
        return {
            "notes_root": str(store.root),
            "client_count": len(store.list_clients()),
            "readable": os.access(store.root, os.R_OK),
            "writable": os.access(store.root, os.W_OK),
            "docker_hint": "A Docker container can only use host folders mounted into it.",
        }

    def update(self, notes_root: object) -> dict:
        if not isinstance(notes_root, str) or not notes_root.strip():
            raise StoreError("Enter an absolute path to your Coaching notes folder")
        new_store = self._validated_store(notes_root)
        self._write_config(new_store.root)
        with self._lock:
            self._store = new_store
        return self.details()

    @staticmethod
    def _validated_store(notes_root: str | Path) -> NotesStore:
        candidate = Path(notes_root).expanduser()
        if not candidate.is_absolute():
            raise StoreError("The vault location must be an absolute path")
        try:
            candidate = candidate.resolve(strict=True)
        except (FileNotFoundError, OSError):
            raise StoreError("That folder does not exist or is not currently mounted")
        if not candidate.is_dir():
            raise StoreError("The vault location must be a folder")
        coaching_notes = candidate / "Coaching notes"
        if coaching_notes.is_dir():
            candidate = coaching_notes.resolve()
        if not os.access(candidate, os.R_OK | os.X_OK):
            raise StoreError("Hearthnote cannot read that folder")
        if not os.access(candidate, os.W_OK):
            raise StoreError("Hearthnote needs write access to save notes")
        try:
            next(candidate.iterdir(), None)
        except OSError:
            raise StoreError("Hearthnote cannot list the contents of that folder")
        return NotesStore(candidate)

    def _read_config(self) -> str | None:
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
            value = payload.get("notes_root")
            return value if isinstance(value, str) and value else None
        except (FileNotFoundError, OSError, json.JSONDecodeError, AttributeError):
            return None

    def _write_config(self, root: Path) -> None:
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(
                prefix=f".{self.config_path.name}.",
                suffix=".tmp",
                dir=self.config_path.parent,
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump({"notes_root": str(root)}, handle, indent=2)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(temporary, 0o600)
                os.replace(temporary, self.config_path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        except OSError as error:
            raise StoreError(f"Could not save the vault setting: {error.strerror or error}")

