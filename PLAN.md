# Plan: GitHub -> Dropbox Refresh + Gmail Draft

## Goal

Build a tiny reproducible bridge that:

1. Detects a new version in a GitHub repo.
2. Replaces a Dropbox folder with a fresh upload of a local folder.
3. Creates a Gmail draft to `oj.watson92@gmail.com` with the new Dropbox share link.

## Design

1. Local runner script (`bridge.py`) polls GitHub API for latest version.
2. If version is new:
   - clear Dropbox target folder (with optional permanent delete);
   - recreate folder;
   - upload all files from local source folder;
   - create/reuse public Dropbox shared link.
3. Create Gmail draft via Gmail API with version + share link.
4. Persist state to `.state/state.json` to avoid duplicate runs.

## Lightweight constraints

1. Python + minimal dependencies only.
2. Free-tier friendly APIs:
   - Dropbox user access token.
   - Gmail OAuth desktop app (draft scope).
3. No server required (can run via cron / Task Scheduler).

## Triggers

1. Manual: run command when needed.
2. Scheduled: run every N minutes; no-op when GitHub version unchanged.

## Safety and idempotency

1. `--dry-run` mode performs planning/logging with no remote writes.
2. State file prevents repeated Dropbox uploads and repeated draft creation for same version.
3. `--force` overrides state for reruns.

## Known constraints

1. Public GitHub repo creation/push requires valid `gh` auth.
2. Dropbox and Gmail live actions require user credentials.
3. Permanent delete behavior depends on Dropbox app scopes/account behavior.
