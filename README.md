# Hearthnote

A small, self-hosted web interface for coaching session notes stored as plain Markdown files.

Hearthnote expects this folder structure:

```text
Coaching notes/
  Client name/
    Session 1.md
    Session 2.md
```

The Markdown files remain the source of truth, so the same folder can still be opened in Obsidian and synchronized with Syncthing.

## Run the demo

Python 3.11+ is the only requirement.

```bash
python -m app.server
```

Open <http://localhost:8000>. By default the app uses the included synthetic notes in `synthetic_data/Coaching notes`.

To use another folder:

```bash
NOTES_ROOT="/path/to/your/vault/Coaching notes" python -m app.server
```

## Run with Docker

```bash
docker compose up --build
```

The Compose example mounts the synthetic data. For your NAS, replace that volume source with the absolute path to your real `Coaching notes` directory:

```yaml
volumes:
  - /mnt/pool/your-vault/Coaching notes:/notes:Z
```

The `Z` suffix supplies the correct SELinux label on hosts that enforce it. If your NAS does not use SELinux, it is harmless with normal Docker; remove it if the platform's volume editor expects only a source and destination.

Keep the app private to your LAN or VPN and put authentication in front of it before using real client notes.

## MVP features

- Client and session discovery from the filesystem
- Searchable client navigation
- Automatic creation of the next `Session n.md`
- Debounced autosave with atomic file replacement
- Conflict detection if another program changes a note while it is open
- Responsive layout for desktop and mobile
- No database and no proprietary file format

## Tests

```bash
python -m unittest discover -s tests -v
```

## Security scope

This MVP intentionally does not include authentication. Bind it only to a trusted network while prototyping. A production deployment should add single-user authentication, HTTPS, backups, and a restricted container mount exposing only the coaching notes folder.

