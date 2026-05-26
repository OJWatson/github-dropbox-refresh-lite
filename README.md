# github-dropbox-refresh-lite

Lightweight reproducible bridge for collaborators who do not use Git:

1. Detect latest GitHub version.
2. Build a reproducible source snapshot from GitHub archive (default).
3. Hard-delete and recreate a Dropbox folder.
4. Upload the full snapshot.
5. Send (or draft) Gmail notification with the Dropbox link.

## Default workflow (OJ)

Defaults are configured for:

1. `SOURCE_MODE=github_archive`
2. `DROPBOX_BACKEND=token`
3. `DROPBOX_PERMANENT_DELETE=true`
4. `GMAIL_BACKEND=local`
5. `GMAIL_ACTION=send`
6. `GMAIL_TO=oj.watson92@gmail.com`

This means the bridge uploads a clean GitHub snapshot for the detected version and sends an email after refresh.

## Project layout

1. `bridge.py`: main runner.
2. `dummy_payload/`: optional local test fixture for `SOURCE_MODE=local_dir`.
3. `.state/state.json`: remembers last processed version and last delivery result.
4. `.env`: configuration (copy from `.env.example`).

## Setup

```bash
cd github-dropbox-refresh-lite
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Required config for default path

1. `GITHUB_OWNER`, `GITHUB_REPO`, `GITHUB_REF`
2. `DROPBOX_ACCESS_TOKEN`
3. Gmail local OAuth files for `GMAIL_BACKEND=local`:
   - `GMAIL_CLIENT_SECRET_FILE` (Desktop OAuth client JSON)
   - writable `GMAIL_TOKEN_FILE` path for refresh token cache

## Source modes

`SOURCE_MODE=github_archive` (default):

1. Detects version according to `GITHUB_VERSION_STRATEGY`.
2. Downloads archive for exact detected ref (`archive_ref`) via GitHub API.
3. Extracts archive and uploads that extracted snapshot.

`SOURCE_MODE=local_dir`:

1. Uses `LOCAL_SOURCE_DIR` directly.
2. Useful for local fixture testing.

## Dropbox backends

`DROPBOX_BACKEND=token` (recommended):

1. Uses official Dropbox SDK token backend directly.
2. Requires `DROPBOX_ACCESS_TOKEN`.

`DROPBOX_BACKEND=maton` (optional):

1. Uses Maton gateway Dropbox endpoints.
2. Requires `MATON_API_KEY`/`MATON_API_KEY_FILE`.

## Gmail backends and action

`GMAIL_ACTION=draft|send`:

1. `send` delivers email.
2. `draft` creates draft only.

`GMAIL_BACKEND=local` (recommended):

1. Uses Gmail API OAuth locally.
2. Supports both `draft` and `send`.

`GMAIL_BACKEND=maton` (optional):

1. Uses Maton Gmail proxy endpoints.
2. Supports `draft` and `send` paths.

`GMAIL_BACKEND=none`:

1. Skips notification.

## GitHub version detection

`GITHUB_VERSION_STRATEGY=commit|release|tag`:

1. `commit`: monitors `GITHUB_REF` commit SHA.
2. `release`: monitors latest release id.
3. `tag`: monitors latest tag result.

Each detected version includes an `archive_ref` used for snapshot download.

## Run

Dry run (no Dropbox/Gmail writes):

```bash
./run.sh --dry-run --force
```

Offline dry run with explicit mock version:

```bash
./run.sh --dry-run --force \
  --mock-version-id local-test-001 \
  --mock-version-label local-test-001 \
  --mock-version-url https://example.invalid/local-test-001 \
  --mock-version-archive-ref local-test-001
```

Local-dir fallback dry run:

```bash
SOURCE_MODE=local_dir LOCAL_SOURCE_DIR=dummy_payload ./run.sh --dry-run --force
```

Live run:

```bash
./run.sh
```

Force run even if version unchanged:

```bash
./run.sh --force
```

## Dropbox refresh behavior

Defaults:

1. `DROPBOX_PERMANENT_DELETE=true`
2. `DROPBOX_FORCE_NEW_SHARE_LINK=true`

On refresh, bridge attempts to:

1. permanently delete old target folder;
2. recreate it;
3. upload fresh snapshot files;
4. revoke old direct links;
5. create a fresh share link.

If your Dropbox app/account does not allow permanent delete, set `DROPBOX_PERMANENT_DELETE=false`.

## Scheduling

Linux cron example (every 15 min):

```bash
*/15 * * * * cd /path/to/github-dropbox-refresh-lite && /path/to/github-dropbox-refresh-lite/.venv/bin/python bridge.py >> bridge.log 2>&1
```

## Notes

1. Keep `.env`, `.state/`, and `secrets/` out of git.
2. For private repos or higher limits, provide `GITHUB_TOKEN`.
3. Use `--dry-run` for non-mutating validation.
