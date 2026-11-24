from __future__ import annotations

import ctypes
import json
import os
import re
import stat
from pathlib import Path
from uuid import uuid4

from .config import VaultManager
from .store import Conflict, NotFound, NotesStore, SESSION_RE, StoreError


TRASH_DIR = ".hearthnote-trash"
TOKEN_RE = re.compile(r"[0-9a-f]{32}")
SOURCE_TYPES = {
    "session": "clients",
    "other-note": "clients",
    "client": "clients",
    "material": "knowledge",
    "topic": "knowledge",
}
FOLDER_KINDS = {"client", "topic"}


def _valid_component(name: str) -> bool:
    return (
        bool(name)
        and not name.startswith(".")
        and not any(char in name for char in "/\\\x00")
        and Path(name).name == name
        and (os.name != "nt" or (":" not in name and name.rstrip(" .") == name))
    )


def _relative_parts(value: object) -> list[str]:
    if not isinstance(value, str):
        raise StoreError("Choose a path inside the selected content folder")
    parts = value.split("/")
    if not all(_valid_component(part) for part in parts):
        raise StoreError("Choose a visible path inside the selected content folder")
    return parts


def _mode(path: Path) -> int:
    try:
        info = path.lstat()
        if os.name == "nt" and info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            return stat.S_IFLNK
        return info.st_mode
    except FileNotFoundError:
        return 0


def _check_target(
    root: Path, boundaries: tuple[Path, ...], parts: list[str], *, allow_parent: bool = False,
) -> Path:
    if not stat.S_ISDIR(_mode(root)):
        raise StoreError("The selected content folder is not a regular directory")
    target = root.joinpath(*parts)
    if any(target.is_relative_to(path) or (not allow_parent and path.is_relative_to(target)) for path in boundaries):
        raise StoreError("That path belongs to or contains another enabled content folder")
    folder = root
    for part in parts[:-1]:
        folder /= part
        if not stat.S_ISDIR(_mode(folder)):
            raise NotFound("The original parent folder is missing or is not a regular directory")
    return target


def _move_target(root: Path, boundaries: tuple[Path, ...], kind: str, payload: dict) -> Path:
    if SOURCE_TYPES[kind] == "clients":
        client = payload.get("client")
        if not isinstance(client, str):
            raise StoreError("Choose a client")
        name = NotesStore._valid_client(client)
        if not _valid_component(name):
            raise StoreError("Client name contains unsupported characters")
        client_dir = _check_target(root, boundaries, [name], allow_parent=kind != "client")
        if not stat.S_ISDIR(_mode(client_dir)):
            raise NotFound("Client not found")
        if kind == "client":
            return client_dir
        store = NotesStore(root)
        if kind == "session":
            number = payload.get("number")
            if type(number) is not int:
                raise StoreError("Session number must be a positive integer")
            parts = [name, store._session_path(name, number).name]
        else:
            filename = _relative_parts(payload.get("filename"))
            if len(filename) != 1:
                raise NotFound("Note not found")
            parts = [name, store._other_note_path(name, filename[0]).name]
    else:
        parts = _relative_parts(payload.get("path"))
    target = _check_target(root, boundaries, parts)
    mode = _mode(target)
    if kind in FOLDER_KINDS:
        if not stat.S_ISDIR(mode):
            raise NotFound("Folder not found")
    elif target.suffix.lower() != ".md" or not stat.S_ISREG(mode):
        raise NotFound("Note or material not found")
    return target


def _trash_folder(root: Path, *, create: bool = False) -> Path:
    if not stat.S_ISDIR(_mode(root)):
        raise StoreError("The selected content folder is not a regular directory")
    folder = root / TRASH_DIR
    if create:
        folder.mkdir(mode=0o700, exist_ok=True)
    if not stat.S_ISDIR(_mode(folder)):
        raise NotFound("A usable trash folder was not found in the selected content folder")
    return folder


def _cleanup(entry: Path) -> None:
    # Never recursively remove anything, even after an interrupted operation.
    try:
        (entry / "entry.json").unlink(missing_ok=True)
        entry.rmdir()
    except OSError:
        pass


def _restore_path(entry: Path, source_type: str) -> tuple[str, list[str]]:
    metadata = entry / "entry.json"
    if not stat.S_ISREG(_mode(metadata)):
        raise NotFound("This item is no longer available to restore")
    record = json.loads(metadata.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise StoreError("The trash record is invalid")
    kind = record.get("kind")
    if not isinstance(kind, str) or SOURCE_TYPES.get(kind) != source_type:
        raise NotFound("This item does not belong to the selected content folder")
    parts = _relative_parts(record.get("path"))
    if source_type == "clients":
        if len(parts) != (1 if kind == "client" else 2) or NotesStore._valid_client(parts[0]) != parts[0]:
            raise StoreError("The trash record is invalid")
    if kind not in FOLDER_KINDS:
        filename = parts[-1]
        if Path(filename).suffix.lower() != ".md" or (
            source_type == "clients" and bool(SESSION_RE.fullmatch(filename)) != (kind == "session")
        ):
            raise StoreError("The trash record is invalid")
    return kind, parts


def _rename_noreplace(original: Path, target: Path) -> None:
    # POSIX rename otherwise replaces files and empty directories, even if a
    # collision appeared after we checked for it. Use the OS's exclusive rename.
    if os.name == "nt":
        original.rename(target)
        return
    libc = ctypes.CDLL(None, use_errno=True)
    source, destination = os.fsencode(original), os.fsencode(target)
    if hasattr(libc, "renameat2"):
        at_fdcwd, rename_noreplace = -100, 1
        result = libc.renameat2(at_fdcwd, source, at_fdcwd, destination, rename_noreplace)
    elif hasattr(libc, "renamex_np"):
        rename_excl = 4
        result = libc.renamex_np(source, destination, rename_excl)
    else:
        raise StoreError("This platform does not support restoring without overwriting existing items")
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def move(vault: VaultManager, source: str | None, payload: dict) -> dict:
    kind = payload.get("kind") if isinstance(payload, dict) else None
    if not isinstance(kind, str) or kind not in SOURCE_TYPES:
        raise StoreError("Choose a supported item to delete")
    try:
        with vault.source_scope(SOURCE_TYPES[kind], source) as (root, boundaries), NotesStore._write_lock:
            target = _move_target(root, boundaries, kind, payload)
            trash = _trash_folder(root, create=True)
            token = uuid4().hex
            entry = trash / token
            entry.mkdir(mode=0o700)
            try:
                record = {"kind": kind, "path": target.relative_to(root).as_posix()}
                with (entry / "entry.json").open("x", encoding="utf-8") as metadata:
                    json.dump(record, metadata)
                target.rename(entry / "item")
            except (OSError, ValueError):
                _cleanup(entry)
                raise
            return {"token": token}
    except (OSError, ValueError) as error:
        raise StoreError("Could not move this item to trash") from error


def restore(vault: VaultManager, source: str | None, payload: dict) -> dict:
    source_type = payload.get("type") if isinstance(payload, dict) else None
    if source_type not in ("clients", "knowledge"):
        raise StoreError("Choose an enabled content folder")
    token = payload.get("token")
    if not isinstance(token, str) or not TOKEN_RE.fullmatch(token):
        raise StoreError("Invalid trash token")
    try:
        with vault.source_scope(source_type, source) as (root, boundaries), NotesStore._write_lock:
            entry = _trash_folder(root) / token
            if not stat.S_ISDIR(_mode(entry)):
                raise NotFound("This item is no longer available to restore")
            kind, parts = _restore_path(entry, source_type)
            item = entry / "item"
            is_expected = stat.S_ISDIR if kind in FOLDER_KINDS else stat.S_ISREG
            if not is_expected(_mode(item)):
                raise NotFound("This item is no longer available to restore")
            target = _check_target(root, boundaries, parts)
            if _mode(target):
                raise Conflict("An item already exists at the original location", {})
            if kind == "session":
                number = int(SESSION_RE.fullmatch(target.name).group(1))
                if number in NotesStore._session_files(target.parent):
                    raise Conflict("A session with this number already exists", {})
            _rename_noreplace(item, target)
            _cleanup(entry)
            return {"restored": True}
    except FileExistsError as error:
        raise Conflict("An item already exists at the original location", {}) from error
    except (OSError, ValueError) as error:
        raise StoreError("Could not restore this item from trash") from error
