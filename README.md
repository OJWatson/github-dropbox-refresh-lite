# github-dropbox-refresh-lite

Super-lightweight bridge for collaborators who do not use Git:

1. Detect latest GitHub version.
2. Delete and recreate a Dropbox folder from local files.
3. Create a Gmail draft to `oj.watson92@gmail.com` with the new Dropbox link.

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

## Credentials

### Dropbox

1. Create a Dropbox app in the Dropbox App Console.
2. Grant file and sharing scopes required for:
   - folder delete/create/upload
   - shared link create/revoke
3. Generate a user access token and set `DROPBOX_ACCESS_TOKEN` in `.env`.

### Gmail Draft API

1. In Google Cloud Console, create OAuth Desktop credentials.
2. Enable Gmail API.
3. Save JSON as `secrets/google_client_secret.json`.
4. First run opens browser auth and stores token at `.state/gmail_token.json`.

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

## Scheduling

Linux cron example (every 15 min):

```bash
*/15 * * * * cd /path/to/github-dropbox-refresh-lite && /path/to/github-dropbox-refresh-lite/.venv/bin/python bridge.py >> bridge.log 2>&1
```

## Notes

1. Keep `.env`, `.state/`, and `secrets/` out of git.
2. If GitHub auth is missing, you can still read public repo versions without `GITHUB_TOKEN`.
3. If Dropbox or Gmail credentials are missing, run with `--dry-run` for validation.
