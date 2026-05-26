# github-dropbox-refresh-lite

Super-lightweight bridge for collaborators who do not use Git:

1. Detect latest GitHub version.
2. Delete and recreate a Dropbox folder from local files.
3. Create a Gmail draft with the new Dropbox link.

Default setup is Maton API Gateway for both Dropbox and Gmail. Legacy Dropbox token and local Gmail OAuth paths are still available.

## What this solves

Instead of manually:

1. deleting old Dropbox folder;
2. clearing deleted files;
3. re-uploading a new folder;
4. emailing a new link;

you run one command.

## Project layout

1. `bridge.py`: main runner.
2. `dummy_payload/`: folder that gets uploaded to Dropbox.
3. `.state/state.json`: remembers the last processed GitHub version.
4. `.env`: configuration (copy from `.env.example`).

## Setup

```bash
cd github-dropbox-refresh-lite
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Backend selection

Set in `.env`:

1. `DROPBOX_BACKEND=maton|token`
2. `GMAIL_BACKEND=maton|local|none`

### Maton-first (recommended)

Use one of:

1. `MATON_API_KEY=...`
2. `MATON_API_KEY_FILE=/absolute/path/to/file`

`MATON_API_KEY` may also be an OpenClaw-style `env://file/absolute/path` pointer.

Optional connection pinning:

1. `MATON_DROPBOX_CONNECTION=<connection_id>`
2. `MATON_GOOGLE_MAIL_CONNECTION=<connection_id>`

If connection IDs are omitted, Maton uses its default active connection for each app.

### Legacy fallback backends

`DROPBOX_BACKEND=token`:

1. Set `DROPBOX_ACCESS_TOKEN`.
2. App must have scopes for folder delete/create/upload and shared link create/revoke.

`GMAIL_BACKEND=local`:

1. Create Google OAuth Desktop credentials.
2. Enable Gmail API.
3. Save JSON to `GMAIL_CLIENT_SECRET_FILE` (default `secrets/google_client_secret.json`).
4. First live run opens browser auth and writes `GMAIL_TOKEN_FILE` (default `.state/gmail_token.json`).

`GMAIL_BACKEND=none`:

1. Skips draft creation entirely.

## Dropbox calls (Maton backend)

The bridge uses `https://gateway.maton.ai/dropbox/2/...` with:

1. `Authorization: Bearer $MATON_API_KEY`
2. `Maton-Connection: <id>` when `MATON_DROPBOX_CONNECTION` is set

Operations used:

1. `users/get_current_account`
2. `files/permanently_delete` or `files/delete_v2`
3. `files/create_folder_v2`
4. `files/upload` and upload-session endpoints
5. `sharing/list_shared_links`
6. `sharing/revoke_shared_link`
7. `sharing/create_shared_link_with_settings`

## Gmail draft calls (Maton backend)

The bridge calls:

1. `POST https://gateway.maton.ai/google-mail/gmail/v1/users/me/drafts`

with body:

```json
{"message":{"raw":"<base64url email bytes>"}}
```

## Run

Dry run (no Dropbox or Gmail writes):

```bash
./run.sh --dry-run --force
```

Offline dry run (no GitHub API call):

```bash
./run.sh --dry-run --force \
  --mock-version-id local-test-001 \
  --mock-version-label local-test-001 \
  --mock-version-url https://example.invalid/local-test-001
```

Backend override examples:

```bash
DROPBOX_BACKEND=token GMAIL_BACKEND=local ./run.sh --dry-run --force
DROPBOX_BACKEND=maton GMAIL_BACKEND=none ./run.sh --dry-run --force
```

Live run:

```bash
./run.sh
```

Force run even if GitHub version unchanged:

```bash
./run.sh --force
```

## GitHub version detection

Defaults:

1. `GITHUB_VERSION_STRATEGY=commit`
2. checks `GITHUB_OWNER/GITHUB_REPO` at `GITHUB_REF`

Supported strategies:

1. `commit`
2. `release`
3. `tag`

## Dropbox behavior

Defaults:

1. `DROPBOX_PERMANENT_DELETE=true`
2. `DROPBOX_FORCE_NEW_SHARE_LINK=true`

This means each refresh attempts to:

1. permanently delete previous target folder;
2. recreate and upload fresh files;
3. revoke old share links;
4. create a new share link.

Note: `files/permanently_delete` can be restricted by Dropbox app/account type. If it fails in your environment, set `DROPBOX_PERMANENT_DELETE=false` to use soft delete (`files/delete_v2`).

## Scheduling

Linux cron example (every 15 min):

```bash
*/15 * * * * cd /path/to/github-dropbox-refresh-lite && /path/to/github-dropbox-refresh-lite/.venv/bin/python bridge.py >> bridge.log 2>&1
```

## Notes

1. Keep `.env`, `.state/`, and `secrets/` out of git.
2. If GitHub auth is missing, you can still read public repo versions without `GITHUB_TOKEN`.
3. If remote credentials are missing, run with `--dry-run` for validation.
