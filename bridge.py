#!/usr/bin/env python3
"""GitHub -> Dropbox refresh bridge with Gmail draft notification."""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

GITHUB_API = "https://api.github.com"
MATON_GATEWAY = "https://gateway.maton.ai"
DEFAULT_STATE_FILE = ".state/state.json"
CHUNK_SIZE = 8 * 1024 * 1024


class BridgeError(RuntimeError):
    """Raised for expected bridge failures."""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_github_remote() -> tuple[str | None, str | None]:
    try:
        proc = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None, None
    if proc.returncode != 0:
        return None, None
    remote = proc.stdout.strip()
    if not remote:
        return None, None
    # git@github.com:owner/repo.git
    if remote.startswith("git@github.com:") and remote.endswith(".git"):
        slug = remote.split(":", 1)[1][:-4]
    # https://github.com/owner/repo(.git)
    elif "github.com/" in remote:
        slug = remote.split("github.com/", 1)[1]
        if slug.endswith(".git"):
            slug = slug[:-4]
    else:
        return None, None
    parts = slug.split("/")
    if len(parts) != 2:
        return None, None
    return parts[0], parts[1]


@dataclass(frozen=True)
class Config:
    github_owner: str
    github_repo: str
    github_ref: str
    github_strategy: str
    github_token: str | None
    local_source_dir: Path
    state_file: Path
    dropbox_backend: str
    dropbox_token: str | None
    dropbox_target_path: str
    dropbox_permanent_delete: bool
    dropbox_force_new_share_link: bool
    gmail_backend: str
    gmail_to: str
    gmail_subject_prefix: str
    gmail_client_secret_file: Path
    gmail_token_file: Path
    maton_api_key: str | None
    maton_dropbox_connection: str | None
    maton_google_mail_connection: str | None
    maton_gateway_base_url: str


@dataclass(frozen=True)
class VersionInfo:
    id: str
    label: str
    html_url: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_secret_from_env_or_file(value_env: str, file_env: str) -> str | None:
    value = os.environ.get(value_env, "").strip()
    if value.startswith("env://file/"):
        file_path = Path(value.removeprefix("env://file")).expanduser()
        if not file_path.exists():
            raise BridgeError(f"{value_env} points to a missing env file: {file_path}")
        secret = file_path.read_text(encoding="utf-8").strip()
        if not secret:
            raise BridgeError(f"{value_env} points to an empty env file: {file_path}")
        return secret
    if value:
        return value
    file_path_raw = os.environ.get(file_env, "").strip()
    if not file_path_raw:
        return None
    file_path = Path(file_path_raw).expanduser()
    if not file_path.exists():
        raise BridgeError(f"{file_env} points to a missing file: {file_path}")
    secret = file_path.read_text(encoding="utf-8").strip()
    if not secret:
        raise BridgeError(f"{file_env} points to an empty file: {file_path}")
    return secret


def optional_env(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def load_config(args: argparse.Namespace) -> Config:
    load_dotenv(Path(".env"))
    owner_fallback, repo_fallback = parse_github_remote()
    github_owner = args.github_owner or os.environ.get("GITHUB_OWNER") or owner_fallback
    github_repo = args.github_repo or os.environ.get("GITHUB_REPO") or repo_fallback
    if not github_owner or not github_repo:
        raise BridgeError(
            "Missing GitHub repo coordinates. Set GITHUB_OWNER and GITHUB_REPO in .env."
        )
    github_ref = args.github_ref or os.environ.get("GITHUB_REF", "main")
    strategy = os.environ.get("GITHUB_VERSION_STRATEGY", "commit").strip().lower()
    if strategy not in {"commit", "release", "tag"}:
        raise BridgeError("GITHUB_VERSION_STRATEGY must be one of: commit, release, tag")
    dropbox_backend = os.environ.get("DROPBOX_BACKEND", "maton").strip().lower()
    if dropbox_backend not in {"maton", "token"}:
        raise BridgeError("DROPBOX_BACKEND must be one of: maton, token")
    gmail_backend = os.environ.get("GMAIL_BACKEND", "maton").strip().lower()
    if gmail_backend not in {"maton", "local", "none"}:
        raise BridgeError("GMAIL_BACKEND must be one of: maton, local, none")
    source_dir = Path(os.environ.get("LOCAL_SOURCE_DIR", "dummy_payload")).resolve()
    state_file = Path(args.state_file or os.environ.get("STATE_FILE", DEFAULT_STATE_FILE))
    maton_api_key = load_secret_from_env_or_file("MATON_API_KEY", "MATON_API_KEY_FILE")
    maton_gateway_base_url = os.environ.get("MATON_GATEWAY_BASE_URL", MATON_GATEWAY).strip()
    if not maton_gateway_base_url:
        raise BridgeError("MATON_GATEWAY_BASE_URL cannot be empty when set.")
    maton_gateway_base_url = maton_gateway_base_url.rstrip("/")
    return Config(
        github_owner=github_owner,
        github_repo=github_repo,
        github_ref=github_ref,
        github_strategy=strategy,
        github_token=os.environ.get("GITHUB_TOKEN"),
        local_source_dir=source_dir,
        state_file=state_file,
        dropbox_backend=dropbox_backend,
        dropbox_token=os.environ.get("DROPBOX_ACCESS_TOKEN"),
        dropbox_target_path=os.environ.get("DROPBOX_TARGET_PATH", "/github-dropbox-refresh-lite"),
        dropbox_permanent_delete=env_bool("DROPBOX_PERMANENT_DELETE", default=True),
        dropbox_force_new_share_link=env_bool("DROPBOX_FORCE_NEW_SHARE_LINK", default=True),
        gmail_backend=gmail_backend,
        gmail_to=os.environ.get("GMAIL_TO", "oj.watson92@gmail.com"),
        gmail_subject_prefix=os.environ.get("GMAIL_SUBJECT_PREFIX", "[Dropbox Refresh]"),
        gmail_client_secret_file=Path(
            os.environ.get("GMAIL_CLIENT_SECRET_FILE", "secrets/google_client_secret.json")
        ),
        gmail_token_file=Path(os.environ.get("GMAIL_TOKEN_FILE", ".state/gmail_token.json")),
        maton_api_key=maton_api_key,
        maton_dropbox_connection=optional_env("MATON_DROPBOX_CONNECTION"),
        maton_google_mail_connection=optional_env("MATON_GOOGLE_MAIL_CONNECTION"),
        maton_gateway_base_url=maton_gateway_base_url,
    )


def github_get_json(path: str, token: str | None = None) -> dict[str, Any] | list[Any]:
    req = urllib.request.Request(
        f"{GITHUB_API}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}" if token else "",
            "User-Agent": "github-dropbox-refresh-lite",
        },
    )
    # Remove empty Authorization header if token absent.
    if not token:
        req.headers.pop("Authorization", None)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise BridgeError(f"GitHub API error {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise BridgeError(f"GitHub API connection failed: {exc}") from exc


def detect_version(cfg: Config) -> VersionInfo:
    base = f"/repos/{cfg.github_owner}/{cfg.github_repo}"
    if cfg.github_strategy == "commit":
        payload = github_get_json(f"{base}/commits/{cfg.github_ref}", cfg.github_token)
        assert isinstance(payload, dict)
        sha = str(payload["sha"])
        return VersionInfo(id=sha, label=sha[:12], html_url=str(payload["html_url"]))
    if cfg.github_strategy == "release":
        payload = github_get_json(f"{base}/releases/latest", cfg.github_token)
        assert isinstance(payload, dict)
        rid = str(payload["id"])
        tag = str(payload.get("tag_name", "release"))
        return VersionInfo(id=rid, label=tag, html_url=str(payload["html_url"]))
    payload = github_get_json(f"{base}/tags?per_page=1", cfg.github_token)
    assert isinstance(payload, list)
    if not payload:
        raise BridgeError("No tags found for repository while using tag strategy.")
    latest = payload[0]
    tag = str(latest["name"])
    sha = str(latest["commit"]["sha"])
    return VersionInfo(
        id=f"{tag}:{sha}",
        label=tag,
        html_url=f"https://github.com/{cfg.github_owner}/{cfg.github_repo}/tree/{sha}",
    )


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _is_not_found(exc: Exception) -> bool:
    return "not_found" in str(exc).lower()


def _is_conflict(exc: Exception) -> bool:
    return "conflict" in str(exc).lower()


def http_json_request(
    url: str,
    *,
    method: str = "POST",
    json_body: Any | None = None,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 60,
) -> dict[str, Any] | list[Any]:
    if json_body is not None and data is not None:
        raise ValueError("Only one of json_body or data may be provided.")
    req_headers = {"User-Agent": "github-dropbox-refresh-lite"}
    if headers:
        req_headers.update(headers)
    body = data
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, method=method, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise BridgeError(f"HTTP {exc.code} calling {url}: {body_text}") from exc
    except urllib.error.URLError as exc:
        raise BridgeError(f"Connection error calling {url}: {exc}") from exc
    if not raw:
        return {}
    parsed = json.loads(raw.decode("utf-8"))
    if isinstance(parsed, (dict, list)):
        return parsed
    raise BridgeError(f"Unexpected non-JSON response from {url}")


def _upload_file_dropbox_token(dbx: Any, local_path: Path, remote_path: str) -> None:
    import dropbox  # Imported lazily to keep dry-run lightweight.

    size = local_path.stat().st_size
    with local_path.open("rb") as handle:
        if size <= CHUNK_SIZE:
            dbx.files_upload(
                handle.read(),
                remote_path,
                mode=dropbox.files.WriteMode.overwrite,
                mute=True,
            )
            return
        start = dbx.files_upload_session_start(handle.read(CHUNK_SIZE))
        cursor = dropbox.files.UploadSessionCursor(session_id=start.session_id, offset=handle.tell())
        commit = dropbox.files.CommitInfo(
            path=remote_path,
            mode=dropbox.files.WriteMode.overwrite,
            mute=True,
        )
        while handle.tell() < size:
            remaining = size - handle.tell()
            if remaining <= CHUNK_SIZE:
                dbx.files_upload_session_finish(handle.read(CHUNK_SIZE), cursor, commit)
                break
            dbx.files_upload_session_append_v2(handle.read(CHUNK_SIZE), cursor)
            cursor.offset = handle.tell()


def _ensure_parent_folders_dropbox_token(dbx: Any, remote_file_path: str, created: set[str]) -> None:
    parts = remote_file_path.strip("/").split("/")[:-1]
    current = ""
    for part in parts:
        current += f"/{part}"
        if current in created:
            continue
        try:
            dbx.files_create_folder_v2(current)
        except Exception as exc:  # noqa: BLE001
            if not _is_conflict(exc):
                raise
        created.add(current)


def _maton_headers(cfg: Config, connection_id: str | None = None) -> dict[str, str]:
    if not cfg.maton_api_key:
        raise BridgeError(
            "Maton backend requires MATON_API_KEY or MATON_API_KEY_FILE for non-dry-run execution."
        )
    headers = {"Authorization": f"Bearer {cfg.maton_api_key}"}
    if connection_id:
        headers["Maton-Connection"] = connection_id
    return headers


def _maton_dropbox_json(
    cfg: Config,
    endpoint: str,
    payload: Any | None,
) -> dict[str, Any] | list[Any]:
    return http_json_request(
        f"{cfg.maton_gateway_base_url}/dropbox/2/{endpoint.lstrip('/')}",
        method="POST",
        json_body=payload,
        headers=_maton_headers(cfg, cfg.maton_dropbox_connection),
    )


def _maton_dropbox_content_upload(
    cfg: Config,
    endpoint: str,
    dropbox_api_arg: dict[str, Any],
    content: bytes,
) -> dict[str, Any] | list[Any]:
    headers = _maton_headers(cfg, cfg.maton_dropbox_connection)
    headers["Content-Type"] = "application/octet-stream"
    headers["Dropbox-API-Arg"] = json.dumps(dropbox_api_arg, separators=(",", ":"))
    return http_json_request(
        f"{cfg.maton_gateway_base_url}/dropbox/2/{endpoint.lstrip('/')}",
        method="POST",
        data=content,
        headers=headers,
        timeout=120,
    )


def _upload_file_dropbox_maton(cfg: Config, local_path: Path, remote_path: str) -> None:
    size = local_path.stat().st_size
    with local_path.open("rb") as handle:
        if size <= CHUNK_SIZE:
            _maton_dropbox_content_upload(
                cfg,
                "files/upload",
                {
                    "path": remote_path,
                    "mode": "overwrite",
                    "autorename": False,
                    "mute": True,
                    "strict_conflict": False,
                },
                handle.read(),
            )
            return
        start = _maton_dropbox_content_upload(
            cfg,
            "files/upload_session/start",
            {"close": False},
            handle.read(CHUNK_SIZE),
        )
        assert isinstance(start, dict)
        session_id = str(start["session_id"])
        offset = handle.tell()
        while handle.tell() < size:
            remaining = size - handle.tell()
            chunk = handle.read(CHUNK_SIZE)
            if remaining <= CHUNK_SIZE:
                _maton_dropbox_content_upload(
                    cfg,
                    "files/upload_session/finish",
                    {
                        "cursor": {"session_id": session_id, "offset": offset},
                        "commit": {
                            "path": remote_path,
                            "mode": "overwrite",
                            "autorename": False,
                            "mute": True,
                            "strict_conflict": False,
                        },
                    },
                    chunk,
                )
                break
            _maton_dropbox_content_upload(
                cfg,
                "files/upload_session/append_v2",
                {"cursor": {"session_id": session_id, "offset": offset}, "close": False},
                chunk,
            )
            offset += len(chunk)


def _ensure_parent_folders_dropbox_maton(cfg: Config, remote_file_path: str, created: set[str]) -> None:
    parts = remote_file_path.strip("/").split("/")[:-1]
    current = ""
    for part in parts:
        current += f"/{part}"
        if current in created:
            continue
        try:
            _maton_dropbox_json(cfg, "files/create_folder_v2", {"path": current, "autorename": False})
        except Exception as exc:  # noqa: BLE001
            if not _is_conflict(exc):
                raise
        created.add(current)


def refresh_dropbox_folder_token(cfg: Config, dry_run: bool = False) -> str:
    if dry_run:
        return f"https://www.dropbox.com/home{cfg.dropbox_target_path}"
    if not cfg.dropbox_token:
        raise BridgeError("DROPBOX_ACCESS_TOKEN is required for DROPBOX_BACKEND=token.")
    if not cfg.local_source_dir.exists():
        raise BridgeError(f"Local source directory not found: {cfg.local_source_dir}")
    import dropbox

    dbx = dropbox.Dropbox(cfg.dropbox_token)
    dbx.users_get_current_account()

    if cfg.dropbox_permanent_delete:
        try:
            dbx.files_permanently_delete(cfg.dropbox_target_path)
        except Exception as exc:  # noqa: BLE001
            if not _is_not_found(exc):
                raise
    else:
        try:
            dbx.files_delete_v2(cfg.dropbox_target_path)
        except Exception as exc:  # noqa: BLE001
            if not _is_not_found(exc):
                raise

    try:
        dbx.files_create_folder_v2(cfg.dropbox_target_path)
    except Exception as exc:  # noqa: BLE001
        if not _is_conflict(exc):
            raise

    created_folders = {cfg.dropbox_target_path}
    files = sorted(path for path in cfg.local_source_dir.rglob("*") if path.is_file())
    for path in files:
        rel = path.relative_to(cfg.local_source_dir).as_posix()
        remote_path = f"{cfg.dropbox_target_path.rstrip('/')}/{rel}"
        _ensure_parent_folders_dropbox_token(dbx, remote_path, created_folders)
        _upload_file_dropbox_token(dbx, path, remote_path)

    links = dbx.sharing_list_shared_links(path=cfg.dropbox_target_path, direct_only=True).links
    if links and cfg.dropbox_force_new_share_link:
        for link in links:
            try:
                dbx.sharing_revoke_shared_link(link.url)
            except Exception:  # noqa: BLE001
                pass
        links = []
    if links:
        return links[0].url
    link = dbx.sharing_create_shared_link_with_settings(cfg.dropbox_target_path)
    return link.url


def refresh_dropbox_folder_maton(cfg: Config, dry_run: bool = False) -> str:
    if dry_run:
        return f"https://www.dropbox.com/home{cfg.dropbox_target_path}"
    if not cfg.local_source_dir.exists():
        raise BridgeError(f"Local source directory not found: {cfg.local_source_dir}")

    _maton_dropbox_json(cfg, "users/get_current_account", None)

    if cfg.dropbox_permanent_delete:
        try:
            _maton_dropbox_json(cfg, "files/permanently_delete", {"path": cfg.dropbox_target_path})
        except Exception as exc:  # noqa: BLE001
            if not _is_not_found(exc):
                raise
    else:
        try:
            _maton_dropbox_json(cfg, "files/delete_v2", {"path": cfg.dropbox_target_path})
        except Exception as exc:  # noqa: BLE001
            if not _is_not_found(exc):
                raise

    try:
        _maton_dropbox_json(
            cfg,
            "files/create_folder_v2",
            {"path": cfg.dropbox_target_path, "autorename": False},
        )
    except Exception as exc:  # noqa: BLE001
        if not _is_conflict(exc):
            raise

    created_folders = {cfg.dropbox_target_path}
    files = sorted(path for path in cfg.local_source_dir.rglob("*") if path.is_file())
    for path in files:
        rel = path.relative_to(cfg.local_source_dir).as_posix()
        remote_path = f"{cfg.dropbox_target_path.rstrip('/')}/{rel}"
        _ensure_parent_folders_dropbox_maton(cfg, remote_path, created_folders)
        _upload_file_dropbox_maton(cfg, path, remote_path)

    raw_links = _maton_dropbox_json(
        cfg,
        "sharing/list_shared_links",
        {"path": cfg.dropbox_target_path, "direct_only": True},
    )
    assert isinstance(raw_links, dict)
    links = raw_links.get("links", [])
    if links and cfg.dropbox_force_new_share_link:
        for link in links:
            url = link.get("url")
            if not url:
                continue
            try:
                _maton_dropbox_json(cfg, "sharing/revoke_shared_link", {"url": url})
            except Exception:  # noqa: BLE001
                pass
        links = []
    if links:
        return str(links[0]["url"])
    created_link = _maton_dropbox_json(
        cfg,
        "sharing/create_shared_link_with_settings",
        {"path": cfg.dropbox_target_path},
    )
    assert isinstance(created_link, dict)
    return str(created_link["url"])


def refresh_dropbox_folder(cfg: Config, dry_run: bool = False) -> str:
    if cfg.dropbox_backend == "maton":
        return refresh_dropbox_folder_maton(cfg, dry_run=dry_run)
    return refresh_dropbox_folder_token(cfg, dry_run=dry_run)


def build_email(version: VersionInfo, dropbox_link: str, cfg: Config) -> EmailMessage:
    msg = EmailMessage()
    msg["To"] = cfg.gmail_to
    msg["Subject"] = f"{cfg.gmail_subject_prefix} {version.label}"
    msg.set_content(
        "\n".join(
            [
                "Hi,",
                "",
                "A new GitHub version was detected and Dropbox was refreshed.",
                "",
                f"Repository: https://github.com/{cfg.github_owner}/{cfg.github_repo}",
                f"Version: {version.label}",
                f"Version URL: {version.html_url}",
                f"Dropbox share link: {dropbox_link}",
                f"Run timestamp (UTC): {now_iso()}",
                "",
                "This is an auto-generated draft. Edit as needed before sending.",
            ]
        )
        + "\n"
    )
    return msg


def create_gmail_draft(cfg: Config, message: EmailMessage, dry_run: bool = False) -> str:
    if cfg.gmail_backend == "none":
        return "disabled"
    if dry_run:
        return "dry-run-draft-id"
    if cfg.gmail_backend == "maton":
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        payload = {"message": {"raw": raw}}
        response = http_json_request(
            f"{cfg.maton_gateway_base_url}/google-mail/gmail/v1/users/me/drafts",
            method="POST",
            json_body=payload,
            headers=_maton_headers(cfg, cfg.maton_google_mail_connection),
        )
        assert isinstance(response, dict)
        return str(response["id"])

    if not cfg.gmail_client_secret_file.exists():
        raise BridgeError(
            f"Gmail client secret file missing: {cfg.gmail_client_secret_file}. "
            "Create OAuth Desktop credentials in Google Cloud and save JSON there."
        )

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    scopes = ["https://www.googleapis.com/auth/gmail.compose"]
    creds = None
    if cfg.gmail_token_file.exists():
        creds = Credentials.from_authorized_user_file(cfg.gmail_token_file.as_posix(), scopes)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                cfg.gmail_client_secret_file.as_posix(), scopes
            )
            creds = flow.run_local_server(port=0)
        cfg.gmail_token_file.parent.mkdir(parents=True, exist_ok=True)
        cfg.gmail_token_file.write_text(creds.to_json(), encoding="utf-8")

    service = build("gmail", "v1", credentials=creds)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    payload = {"message": {"raw": raw}}
    created = service.users().drafts().create(userId="me", body=payload).execute()
    return str(created["id"])


def run_once(
    cfg: Config,
    force: bool,
    dry_run: bool,
    version_override: VersionInfo | None = None,
) -> dict[str, Any]:
    version = version_override or detect_version(cfg)
    state = load_state(cfg.state_file)
    last_version = state.get("last_processed_version")
    if last_version == version.id and not force:
        return {
            "ok": True,
            "changed": False,
            "message": "No new GitHub version detected.",
            "version": version.to_dict(),
            "state_file": cfg.state_file.as_posix(),
        }

    dropbox_link = refresh_dropbox_folder(cfg, dry_run=dry_run)
    message = build_email(version, dropbox_link, cfg)
    draft_id = create_gmail_draft(cfg, message, dry_run=dry_run)

    updated_state = {
        "last_processed_version": version.id,
        "last_label": version.label,
        "last_version_url": version.html_url,
        "last_dropbox_link": dropbox_link,
        "last_gmail_draft_id": draft_id,
        "last_run_utc": now_iso(),
    }
    save_state(cfg.state_file, updated_state)
    return {
        "ok": True,
        "changed": True,
        "dry_run": dry_run,
        "version": version.to_dict(),
        "dropbox_link": dropbox_link,
        "email_preview": message.as_string() if dry_run else None,
        "gmail_draft_id": draft_id,
        "state_file": cfg.state_file.as_posix(),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github-owner")
    parser.add_argument("--github-repo")
    parser.add_argument("--github-ref")
    parser.add_argument("--state-file")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--mock-version-id")
    parser.add_argument("--mock-version-label")
    parser.add_argument("--mock-version-url")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    override = None
    if args.mock_version_id:
        override = VersionInfo(
            id=args.mock_version_id,
            label=args.mock_version_label or args.mock_version_id[:12],
            html_url=args.mock_version_url or "https://example.invalid/mock-version",
        )
    try:
        cfg = load_config(args)
        result = run_once(cfg, force=args.force, dry_run=args.dry_run, version_override=override)
    except BridgeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"unexpected: {exc}"}, indent=2))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
