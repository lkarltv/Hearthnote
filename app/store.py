from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


SESSION_RE = re.compile(r"^Session ([1-9][0-9]*)\.md$")
SAFE_NAME_RE = re.compile(r"^[^/\\\x00]{1,100}$")


class StoreError(Exception):
    status = 400


class NotFound(StoreError):
    status = 404


class Conflict(StoreError):
    status = 409

    def __init__(self, message: str, current: dict):
        super().__init__(message)
        self.current = current


@dataclass(frozen=True)
class SessionSummary:
    number: int
    filename: str
    modified_at: str


class NotesStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._write_lock = Lock()

    @staticmethod
    def _valid_client(name: str) -> str:
        name = name.strip()
        if not SAFE_NAME_RE.fullmatch(name) or name in {".", ".."} or name.startswith("."):
            raise StoreError("Client name contains unsupported characters")
        return name

    def _client_dir(self, client: str) -> Path:
        return self.root / self._valid_client(client)

    def _session_path(self, client: str, number: int) -> Path:
        if not isinstance(number, int) or number < 1:
            raise StoreError("Session number must be a positive integer")
        return self._client_dir(client) / f"Session {number}.md"

    @staticmethod
    def _iso(timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()

    @staticmethod
    def _etag(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def list_sessions(self, client: str) -> list[dict]:
        directory = self._client_dir(client)
        if not directory.is_dir():
            raise NotFound("Client not found")
        sessions: list[SessionSummary] = []
        for path in directory.iterdir():
            match = SESSION_RE.fullmatch(path.name) if path.is_file() else None
            if match:
                sessions.append(
                    SessionSummary(
                        number=int(match.group(1)),
                        filename=path.name,
                        modified_at=self._iso(path.stat().st_mtime),
                    )
                )
        sessions.sort(key=lambda session: session.number, reverse=True)
        return [asdict(session) for session in sessions]

    @staticmethod
    def _is_other_note(path: Path) -> bool:
        return (
            path.suffix.lower() == ".md"
            and not SESSION_RE.fullmatch(path.name)
            and not path.is_symlink()
            and path.is_file()
        )

    def list_other_notes(self, client: str) -> list[dict]:
        directory = self._client_dir(client)
        if not directory.is_dir():
            raise NotFound("Client not found")
        if directory.is_symlink():
            return []
        notes = []
        for path in sorted(directory.iterdir(), key=lambda item: (item.name.casefold(), item.name)):
            if self._is_other_note(path):
                try:
                    timestamp = path.stat().st_mtime
                except FileNotFoundError:
                    continue
                notes.append({"filename": path.name, "modified_at": self._iso(timestamp)})
        return notes

    def _other_note_path(self, client: str, filename: str) -> Path:
        directory = self._client_dir(client)
        if not filename or Path(filename).name != filename or "\x00" in filename:
            raise NotFound("Note not found")
        path = directory / filename
        if directory.is_symlink() or not self._is_other_note(path):
            raise NotFound("Note not found")
        return path

    def read_other_note(self, client: str, filename: str) -> dict:
        return self._read_note(self._other_note_path(client, filename))

    def _read_note(self, path: Path) -> dict:
        try:
            content = path.read_text(encoding="utf-8")
            modified_at = self._iso(path.stat().st_mtime)
        except FileNotFoundError:
            raise NotFound("Note not found") from None
        except UnicodeDecodeError:
            raise StoreError("This note is not valid UTF-8") from None
        return {
            "filename": path.name,
            "content": content,
            "etag": self._etag(content),
            "modified_at": modified_at,
        }

    def list_clients(self) -> list[dict]:
        clients = []
        for directory in self.root.iterdir():
            if not directory.is_dir() or directory.name.startswith("."):
                continue
            sessions = self.list_sessions(directory.name)
            latest = sessions[0] if sessions else None
            clients.append(
                {
                    "name": directory.name,
                    "initials": "".join(part[0].upper() for part in directory.name.split()[:2]),
                    "session_count": len(sessions),
                    "latest_session": latest["number"] if latest else None,
                    "modified_at": latest["modified_at"] if latest else None,
                }
            )
        clients.sort(key=lambda client: (client["modified_at"] or "", client["name"]), reverse=True)
        return clients

    def create_client(self, name: str) -> dict:
        directory = self._client_dir(name)
        if directory.exists():
            raise Conflict("A client with this name already exists", {})
        directory.mkdir()
        return {"name": directory.name}

    def read_session(self, client: str, number: int) -> dict:
        path = self._session_path(client, number)
        if not path.is_file():
            raise NotFound("Session not found")
        return {"client": client, "number": number, **self._read_note(path)}

    def create_session(self, client: str) -> dict:
        directory = self._client_dir(client)
        if not directory.is_dir():
            raise NotFound("Client not found")
        numbers = [session["number"] for session in self.list_sessions(client)]
        number = max(numbers, default=0) + 1
        today = datetime.now().astimezone().strftime("%B %-d, %Y")
        content = (
            f"# Session {number}\n\n"
            f"**Date:** {today}\n\n"
            "## Arrival\n\n"
            "\n\n## What we explored\n\n"
            "\n\n## Commitments\n\n"
            "- [ ] \n\n"
            "## Threads for next time\n\n"
        )
        path = self._session_path(client, number)
        self._atomic_write(path, content, exclusive=True)
        return self.read_session(client, number)

    def update_session(self, client: str, number: int, content: str, expected_etag: str) -> dict:
        path = self._session_path(client, number)
        return self._update_note(path, content, expected_etag, client=client, number=number)

    def update_other_note(self, client: str, filename: str, content: str, expected_etag: str) -> dict:
        return self._update_note(self._other_note_path(client, filename), content, expected_etag)

    def _update_note(self, path: Path, content: str, expected_etag: str, **metadata) -> dict:
        if not isinstance(content, str):
            raise StoreError("Content must be text")
        if len(content.encode("utf-8")) > 2_000_000:
            raise StoreError("Note is too large")
        with self._write_lock:
            if not path.is_file():
                raise NotFound("Note not found")
            current = self._read_note(path)
            if not expected_etag or expected_etag != current["etag"]:
                raise Conflict("This note changed somewhere else", {**metadata, **current})
            self._atomic_write(path, content)
            return {**metadata, **self._read_note(path)}

    @staticmethod
    def _atomic_write(path: Path, content: str, exclusive: bool = False) -> None:
        if exclusive and path.exists():
            raise Conflict("Session already exists", {})
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            if exclusive and path.exists():
                raise Conflict("Session already exists", {})
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

