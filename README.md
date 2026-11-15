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

Click the gear beside **Vault connected** to choose your Obsidian vault or its `Coaching notes` folder. Hearthnote validates read/write access before switching and remembers the selection in `~/.config/hearthnote/settings.json`.

You can also set the initial location from the terminal:

```bash
NOTES_ROOT="/path/to/your/obsidian-vault" python -m app.server
```

## Run with Docker

```bash
docker compose up --build
```

Containers cannot browse arbitrary host paths. Set the host vault path before starting Compose:

```bash
HEARTHNOTE_VAULT_PATH="/absolute/path/to/your/obsidian-vault" docker compose up --build -d
```

The vault appears inside the container as `/vault`; that is the path shown in the settings screen. The named `hearthnote-config` volume remembers settings across container replacements. The Compose file's `Z` suffix supplies the correct SELinux label on hosts that enforce it. Remove it if your NAS volume editor expects only a source and destination.

To avoid retyping the path, create an untracked `.env` file:

```dotenv
HEARTHNOTE_VAULT_PATH="/absolute/path/to/your/obsidian-vault"
```

If you deploy through a NAS UI, add two mounts:

- Your Obsidian vault on the host → `/vault` in the container, read/write
- A persistent app-data directory or volume → `/config` in the container, read/write

Keep the app private to your LAN or VPN and put authentication in front of it before using real client notes.

## MVP features

- Client and session discovery from the filesystem
- Configurable, persisted Obsidian vault location
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

