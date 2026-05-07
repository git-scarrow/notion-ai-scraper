"""
connections.py — Inspectable auth connection records.

Inspired by Composio's connection model: a single read-only surface that
answers "what auth do I have, where did it come from, when was it last
refreshed, what surface does it grant access to."

SECURITY: Never reads or stores token bytes. `present: True` is the only
positive signal. All inspection is filesystem-metadata + env-var-key based.
"""

from __future__ import annotations

import glob
import os
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from typing import Literal

try:
    from . import config as _config_mod
except ImportError:
    import config as _config_mod  # type: ignore[no-redef]


Source = Literal["firefox_cookie", "token_file", "env_var", "missing"]

_STALE_AFTER_SECONDS = 7 * 24 * 60 * 60
_NOTION_TOKEN_FILE = os.path.expanduser("~/.notion-token-v2")
_FIREFOX_COOKIES_GLOB = os.path.expanduser("~/.mozilla/firefox/*/cookies.sqlite")


@dataclass
class ConnectionRecord:
    name: str
    surface: str
    source: Source
    source_path: str | None
    present: bool
    freshness_seconds: float | None
    workspace: str | None
    workspace_name: str | None
    identity: str | None
    notes: str

    def to_dict(self) -> dict:
        return asdict(self)


def _file_age_seconds(path: str) -> float | None:
    try:
        return max(0.0, time.time() - os.path.getmtime(path))
    except OSError:
        return None


def _firefox_db_with_notion_cookie() -> tuple[str | None, bool, str | None]:
    """Return (best_db_path, has_token_v2, notion_user_id) without reading
    token_v2 bytes. notion_user_id is non-secret and useful for identity."""
    candidates = sorted(glob.glob(_FIREFOX_COOKIES_GLOB), key=lambda p: os.path.getmtime(p), reverse=True)
    if not candidates:
        return None, False, None
    for db_path in candidates:
        try:
            import shutil
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                shutil.copy2(db_path, tmp_path)
                conn = sqlite3.connect(tmp_path)
                try:
                    rows = conn.execute(
                        "SELECT name, CASE WHEN name='notion_user_id' THEN value ELSE NULL END "
                        "FROM moz_cookies "
                        "WHERE host LIKE '%notion.so' AND name IN ('token_v2', 'notion_user_id')"
                    ).fetchall()
                finally:
                    conn.close()
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        except (OSError, sqlite3.Error):
            continue
        names = {n for n, _ in rows}
        user_id = next((v for n, v in rows if n == "notion_user_id" and v), None)
        if "token_v2" in names:
            return db_path, True, user_id
    return candidates[0], False, None


def _workspace_info() -> tuple[str | None, str | None]:
    space_id: str | None = None
    workspace_name: str | None = None
    try:
        cfg = _config_mod.get_config()
        space_id = cfg.space_id or None
    except Exception:
        space_id = os.environ.get("NOTION_SPACE_ID") or None
    try:
        import json
        path = _config_mod.TEMPLATE_DATA_JSON
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            ws = data.get("workspace") or {}
            workspace_name = ws.get("name") or ws.get("workspace_name")
            if not space_id:
                space_id = ws.get("space_id") or None
    except Exception:
        pass
    return space_id, workspace_name


def inspect_notion_internal_api() -> ConnectionRecord:
    """Internal Notion API auth: token_v2 cookie used by saveTransactionsFanout,
    publishCustomAgentVersion, agent chat, etc.

    Probe order matches mcp_server._get_auth cascade for source attribution,
    but reports the FIRST resolvable source rather than the runtime cache state.
    """
    space_id, workspace_name = _workspace_info()

    if os.environ.get("NOTION_TOKEN_V2"):
        return ConnectionRecord(
            name="notion_internal_api",
            surface="Notion internal API (saveTransactionsFanout, publishCustomAgentVersion, agent chat)",
            source="env_var",
            source_path="$NOTION_TOKEN_V2",
            present=True,
            freshness_seconds=0.0,
            workspace=space_id,
            workspace_name=workspace_name,
            identity=os.environ.get("NOTION_USER_ID"),
            notes="env var present (process lifetime)",
        )

    if os.path.exists(_NOTION_TOKEN_FILE):
        age = _file_age_seconds(_NOTION_TOKEN_FILE)
        return ConnectionRecord(
            name="notion_internal_api",
            surface="Notion internal API (saveTransactionsFanout, publishCustomAgentVersion, agent chat)",
            source="token_file",
            source_path=_NOTION_TOKEN_FILE,
            present=True,
            freshness_seconds=age,
            workspace=space_id,
            workspace_name=workspace_name,
            identity=None,
            notes="token file present; mcp_server applies 5-min in-process cache",
        )

    db_path, has_token, user_id = _firefox_db_with_notion_cookie()
    if db_path and has_token:
        return ConnectionRecord(
            name="notion_internal_api",
            surface="Notion internal API (saveTransactionsFanout, publishCustomAgentVersion, agent chat)",
            source="firefox_cookie",
            source_path=db_path,
            present=True,
            freshness_seconds=_file_age_seconds(db_path),
            workspace=space_id,
            workspace_name=workspace_name,
            identity=user_id,
            notes="extracted from Firefox cookies.sqlite (token_v2)",
        )

    return ConnectionRecord(
        name="notion_internal_api",
        surface="Notion internal API (saveTransactionsFanout, publishCustomAgentVersion, agent chat)",
        source="missing",
        source_path=None,
        present=False,
        freshness_seconds=None,
        workspace=space_id,
        workspace_name=workspace_name,
        identity=None,
        notes="no NOTION_TOKEN_V2 env, no ~/.notion-token-v2, no token_v2 in Firefox cookies",
    )


def inspect_notion_public_api() -> ConnectionRecord:
    """Public Notion REST API auth: NOTION_TOKEN integration token used by
    notion_api.NotionAPIClient, dashboard_server, lab_auditor."""
    space_id, workspace_name = _workspace_info()
    token_present = bool(os.environ.get("NOTION_TOKEN"))
    return ConnectionRecord(
        name="notion_public_api",
        surface="Notion public REST API (databases, pages, blocks via api.notion.com)",
        source="env_var" if token_present else "missing",
        source_path="$NOTION_TOKEN" if token_present else None,
        present=token_present,
        freshness_seconds=0.0 if token_present else None,
        workspace=space_id,
        workspace_name=workspace_name,
        identity=None,
        notes="integration token from environment" if token_present else "NOTION_TOKEN not set in environment",
    )


def inspect_claude_projects() -> ConnectionRecord:
    """Claude.ai Projects auth: sessionKey cookie from Firefox used by
    cli/claude_client.py for the internal web API."""
    candidates = sorted(glob.glob(_FIREFOX_COOKIES_GLOB), key=lambda p: os.path.getmtime(p), reverse=True)
    db_path: str | None = None
    has_session = False
    for cand in candidates:
        try:
            import shutil
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                shutil.copy2(cand, tmp_path)
                conn = sqlite3.connect(tmp_path)
                try:
                    rows = conn.execute(
                        "SELECT name FROM moz_cookies WHERE host LIKE '%claude.ai'"
                    ).fetchall()
                finally:
                    conn.close()
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        except (OSError, sqlite3.Error):
            continue
        names = {n for (n,) in rows}
        if "sessionKey" in names:
            db_path = cand
            has_session = True
            break

    if has_session and db_path:
        return ConnectionRecord(
            name="claude_projects",
            surface="Claude.ai Projects internal web API (sync, chats, knowledge files)",
            source="firefox_cookie",
            source_path=db_path,
            present=True,
            freshness_seconds=_file_age_seconds(db_path),
            workspace=None,
            workspace_name=None,
            identity=None,
            notes="sessionKey cookie present for claude.ai",
        )

    return ConnectionRecord(
        name="claude_projects",
        surface="Claude.ai Projects internal web API (sync, chats, knowledge files)",
        source="missing",
        source_path=None,
        present=False,
        freshness_seconds=None,
        workspace=None,
        workspace_name=None,
        identity=None,
        notes="no sessionKey cookie for claude.ai in any Firefox profile",
    )


_INSPECTORS = (
    inspect_notion_internal_api,
    inspect_notion_public_api,
    inspect_claude_projects,
)


def inspect_all() -> list[ConnectionRecord]:
    return [fn() for fn in _INSPECTORS]


def health_summary() -> dict:
    records = inspect_all()
    healthy = 0
    stale = 0
    missing = 0
    for r in records:
        if not r.present:
            missing += 1
            continue
        if r.freshness_seconds is not None and r.freshness_seconds > _STALE_AFTER_SECONDS:
            stale += 1
        else:
            healthy += 1
    return {
        "healthy": healthy,
        "stale": stale,
        "missing": missing,
        "records": [r.to_dict() for r in records],
    }


def register_connection_tools(mcp) -> None:
    """Attach inspect_connections() and connection_health() to a FastMCP server.

    Call once near other tool registrations in cli/mcp_server.py.
    """

    @mcp.tool()
    def inspect_connections() -> list[dict]:
        """List auth connection records (source, freshness, workspace) — no token bytes."""
        return [r.to_dict() for r in inspect_all()]

    @mcp.tool()
    def connection_health() -> dict:
        """Aggregate auth health: counts of healthy/stale/missing connections."""
        return health_summary()
