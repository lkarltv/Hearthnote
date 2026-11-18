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

On first launch, create a username and password for the single Hearthnote account. Future visits open the sign-in screen when there is no active session. Use **Sign out** at the bottom of the Clients panel to end the current session.

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

The Compose file mounts the named `hearthnote-data` volume at `/data` for the account and login sessions. Keep this volume when you replace or update the container. In a NAS container manager, add a separate persistent read/write mount at `/data`. For a direct Python run, account data goes in `.hearthnote/` next to the app. Set `HEARTHNOTE_DATA_DIR` to use a different location. Keep that directory outside the notes folder. If you run the container as a custom user, give it write access to both mounts.

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

Complete first-run setup on a trusted network. Until the account exists, anyone who can reach the server can claim it. For real client notes, serve Hearthnote through HTTPS on a private LAN or VPN. When using an HTTPS reverse proxy, preserve the incoming `Host` header, set `HEARTHNOTE_SECURE_COOKIE=1` in the container, and restrict direct access to the app port.

