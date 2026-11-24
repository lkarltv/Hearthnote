from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

from .store import NotFound, NotesStore, StoreError


@dataclass(frozen=True)
class Source:
    path: str
    type: str

    @property
    def name(self) -> str:
        if self.path == ".":
            return "Clients" if self.type == "clients" else "Knowledge"
        return Path(self.path).name


class VaultManager:
    """Keeps the active root and its selected folders together."""

    def __init__(self, default_root: str | Path, config_path: str | Path, boundary: str | None = None):
        self.config_path = Path(config_path).expanduser().resolve()
        self.boundary = Path(boundary).resolve() if boundary else None
        self._lock = threading.RLock()
        payload = self._read_config()
        for location in (payload.get("notes_root"), str(default_root)):
            try:
                self._root = self._validated_root(location)
                break
            except StoreError:
                continue
        else:
            self._root = Path(default_root).expanduser().resolve()
        configured = payload.get("sources") if str(self._root) == payload.get("notes_root") else None
        self._sources = self._suggest_sources(self._root)
        if isinstance(configured, list):
            try:
                self._sources = self._parse_sources(configured)
            except StoreError:
                pass

    @property
    def store(self) -> NotesStore:
        return self.client_store()

    def client_store(self, source: str | None = None) -> NotesStore:
        return NotesStore(self.source_folder("clients", source))

    def source_folder(self, kind: str, source: str | None) -> Path:
        with self._lock:
            match = next((
                item for item in self._sources
                if item.type == kind and (source is None or item.path == source)
            ), None)
            if match is None:
                raise NotFound("That content folder is not enabled")
            return self._source_folder(self._root, match.path)

    def details(self) -> dict:
        with self._lock:
            root = self._root
            sources = self._sources
            client_count = 0
            for item in sources:
                if item.type == "clients":
                    try:
                        client_count += len(self.client_store(item.path).list_clients())
                    except (StoreError, OSError):
                        continue
            return {
                "notes_root": str(root),
                "sources": [self._source_details(item) for item in sources],
                "client_count": client_count,
                "readable": os.access(root, os.R_OK),
                "writable": os.access(root, os.W_OK),
                "docker_hint": "A Docker container can only use host folders mounted into it.",
            }

    def browse(self, notes_root: object, parent: str = ".") -> dict:
        root = self._validated_root(notes_root)
        folder = self._source_folder(root, parent)
        try:
            children = sorted(
                (path for path in folder.iterdir()
                 if not path.name.startswith(".") and not path.is_symlink() and path.is_dir()),
                key=lambda path: (path.name.casefold(), path.name),
            )
        except OSError as error:
            raise StoreError("Hearthnote cannot list the contents of that folder") from error
        return {
            "notes_root": str(root),
            "folders": [{"path": path.relative_to(root).as_posix(), "name": path.name} for path in children],
            "suggested_sources": [self._source_details(item) for item in self._suggest_sources(root)],
        }

    def update(self, notes_root: object, sources: object = None) -> dict:
        root = self._validated_root(notes_root)
        with self._lock:
            if sources is None:
                selected = self._sources if root == self._root else self._suggest_sources(root)
            else:
                selected = self._parse_sources(sources)
            for item in selected:
                folder = self._source_folder(root, item.path)
                if item.type == "clients" and not os.access(folder, os.W_OK):
                    raise StoreError(f"Hearthnote needs write access to the Clients folder: {item.path}")
            self._write_config(root, selected)
            self._root = root
            self._sources = selected
            return self.details()

    @staticmethod
    def _source_details(source: Source) -> dict:
        return {**asdict(source), "name": source.name}

    @staticmethod
    def _parse_sources(sources: object) -> tuple[Source, ...]:
        if not isinstance(sources, list):
            raise StoreError("Content folders must be a list")
        result = []
        paths = set()
        for item in sources:
            if not isinstance(item, dict) or item.get("type") not in ("clients", "knowledge"):
                raise StoreError("Choose Clients or Knowledge for each folder")
            path = item.get("path")
            if not isinstance(path, str) or not path or path in paths:
                raise StoreError("Choose each content folder once")
            paths.add(path)
            result.append(Source(path, item["type"]))
        return tuple(result)

    @staticmethod
    def _suggest_sources(root: Path) -> tuple[Source, ...]:
        def available(name: str) -> bool:
            path = root / name
            return path.is_dir() and not path.is_symlink()

        clients = next((name for name in ("Clients", "Coaching notes") if available(name)), None)
        sources = [Source(clients, "clients")] if clients else []
        sources.extend(
            Source(name, "knowledge")
            for name in ("Educational materials", "Worksheet bases")
            if available(name)
        )
        return tuple(sources) or (Source(".", "clients"),)

    @staticmethod
    def _source_folder(root: Path, relative: str) -> Path:
        if relative == ".":
            parts = []
        else:
            parts = relative.split("/")
            if any(not part or part.startswith(".") or "\\" in part or "\x00" in part for part in parts):
                raise StoreError("Choose a folder inside your coaching root")
        folder = root
        for part in parts:
            folder /= part
            if folder.is_symlink():
                raise StoreError("Choose a folder inside your coaching root")
        if not folder.is_dir() or not os.access(folder, os.R_OK | os.X_OK):
            raise StoreError(f"That content folder is missing or cannot be read: {relative}")
        return folder

    def _validated_root(self, notes_root: object) -> Path:
        if not isinstance(notes_root, str) or not notes_root.strip():
            raise StoreError("Enter an absolute path to your coaching folder")
        candidate = Path(notes_root).expanduser()
        if not candidate.is_absolute():
            raise StoreError("The coaching root must be an absolute path")
        try:
            candidate = candidate.resolve(strict=True)
            if self.boundary and not candidate.is_relative_to(self.boundary):
                raise StoreError("Choose a location inside the mounted coaching folder")
            if not candidate.is_dir():
                raise StoreError("The coaching root must be a folder")
            folder_names = ("Clients", "Educational materials", "Worksheet bases")
            if not any((candidate / name).is_dir() for name in folder_names):
                for name in ("Coaching", "Coaching notes"):
                    child = candidate / name
                    if child.is_dir() and not child.is_symlink():
                        candidate = child
                        break
            if not os.access(candidate, os.R_OK | os.X_OK):
                raise StoreError("Hearthnote cannot read that folder")
            next(candidate.iterdir(), None)
        except (OSError, ValueError, RuntimeError):
            raise StoreError("That folder does not exist or is not currently mounted") from None
        return candidate

    def _read_config(self) -> dict:
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write_config(self, root: Path, sources: tuple[Source, ...]) -> None:
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(
                prefix=f".{self.config_path.name}.", suffix=".tmp", dir=self.config_path.parent,
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(
                        {"notes_root": str(root), "sources": [asdict(item) for item in sources]},
                        handle,
                        indent=2,
                    )
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.config_path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        except OSError as error:
            raise StoreError(f"Could not save vault settings: {error.strerror or error}") from error
