from pathlib import Path

from .store import NotFound, StoreError


def _material(path: Path, root: Path) -> dict:
    return {"path": path.relative_to(root).as_posix(), "title": path.stem}


def list_topics(root: Path) -> list[dict]:
    def visit(folder: Path):
        children = sorted(folder.iterdir(), key=lambda path: (path.name.casefold(), path.name))
        visible = [path for path in children if not path.name.startswith(".") and not path.is_symlink()]
        materials = [_material(path, root) for path in visible if path.suffix.lower() == ".md" and path.is_file()]
        if materials:
            yield {"path": folder.relative_to(root).as_posix(), "materials": materials}
        for path in visible:
            if path.is_dir():
                yield from visit(path)

    try:
        return list(visit(root))
    except OSError as error:
        raise StoreError("Could not list the knowledge folder") from error


def read_material(root: Path, relative: str) -> dict:
    parts = relative.split("/")
    path = root
    for part in parts:
        if not part or part.startswith(".") or "\\" in part or "\x00" in part:
            raise NotFound("Material not found")
        path /= part
        if path.is_symlink():
            raise NotFound("Material not found")
    if path.suffix.lower() != ".md" or not path.is_file():
        raise NotFound("Material not found")
    try:
        return {**_material(path, root), "content": path.read_text(encoding="utf-8")}
    except (OSError, UnicodeError) as error:
        raise StoreError("Could not read this Markdown file") from error
