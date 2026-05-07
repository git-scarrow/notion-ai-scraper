"""Tests for cli/connections.py — read-only auth inspection."""

from __future__ import annotations

import os
import sys
import sqlite3

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import connections  # noqa: E402
from connections import (  # noqa: E402
    ConnectionRecord,
    health_summary,
    inspect_all,
    inspect_claude_projects,
    inspect_notion_internal_api,
    inspect_notion_public_api,
)


_RECORD_FIELDS = {
    "name",
    "surface",
    "source",
    "source_path",
    "present",
    "freshness_seconds",
    "workspace",
    "workspace_name",
    "identity",
    "notes",
}


def _assert_full_record(rec: ConnectionRecord) -> None:
    assert isinstance(rec, ConnectionRecord)
    d = rec.to_dict()
    assert set(d.keys()) == _RECORD_FIELDS
    assert isinstance(rec.name, str) and rec.name
    assert isinstance(rec.surface, str) and rec.surface
    assert rec.source in {"firefox_cookie", "token_file", "env_var", "missing"}
    assert isinstance(rec.notes, str)
    if rec.present:
        assert rec.source != "missing"
    else:
        assert rec.source == "missing"
        assert rec.source_path is None
        assert rec.freshness_seconds is None


def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("NOTION_TOKEN_V2", "NOTION_USER_ID", "NOTION_TOKEN", "NOTION_SPACE_ID"):
        monkeypatch.delenv(var, raising=False)


def _empty_firefox(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(connections, "_FIREFOX_COOKIES_GLOB", str(tmp_path / "no-firefox" / "*.sqlite"))


def _firefox_with_cookies(tmp_path, names: list[str], host: str = "www.notion.so") -> str:
    profile = tmp_path / "abc.default"
    profile.mkdir(parents=True, exist_ok=True)
    db = profile / "cookies.sqlite"
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "CREATE TABLE moz_cookies (name TEXT, value TEXT, host TEXT, lastAccessed INTEGER)"
        )
        for n in names:
            value = "user-uuid-1234" if n == "notion_user_id" else "REDACTED"
            conn.execute(
                "INSERT INTO moz_cookies (name, value, host, lastAccessed) VALUES (?, ?, ?, 0)",
                (n, value, host),
            )
        conn.commit()
    finally:
        conn.close()
    return str(db)


def test_inspect_notion_internal_api_env_source(monkeypatch, tmp_path):
    _isolate_env(monkeypatch)
    _empty_firefox(monkeypatch, tmp_path)
    monkeypatch.setattr(connections, "_NOTION_TOKEN_FILE", str(tmp_path / "missing-token"))
    monkeypatch.setenv("NOTION_TOKEN_V2", "REDACTED-test-token")
    monkeypatch.setenv("NOTION_USER_ID", "id-from-env")

    rec = inspect_notion_internal_api()
    _assert_full_record(rec)
    assert rec.source == "env_var"
    assert rec.source_path == "$NOTION_TOKEN_V2"
    assert rec.present is True
    assert rec.identity == "id-from-env"


def test_inspect_notion_internal_api_token_file(monkeypatch, tmp_path):
    _isolate_env(monkeypatch)
    _empty_firefox(monkeypatch, tmp_path)
    token_file = tmp_path / "token-file"
    token_file.write_text("REDACTED\n")
    monkeypatch.setattr(connections, "_NOTION_TOKEN_FILE", str(token_file))

    rec = inspect_notion_internal_api()
    _assert_full_record(rec)
    assert rec.source == "token_file"
    assert rec.source_path == str(token_file)
    assert rec.freshness_seconds is not None and rec.freshness_seconds >= 0


def test_inspect_notion_internal_api_firefox(monkeypatch, tmp_path):
    _isolate_env(monkeypatch)
    monkeypatch.setattr(connections, "_NOTION_TOKEN_FILE", str(tmp_path / "missing-token"))
    profiles = tmp_path / "ff"
    profiles.mkdir()
    _firefox_with_cookies(profiles, ["token_v2", "notion_user_id"])
    monkeypatch.setattr(connections, "_FIREFOX_COOKIES_GLOB", str(profiles / "*" / "cookies.sqlite"))

    rec = inspect_notion_internal_api()
    _assert_full_record(rec)
    assert rec.source == "firefox_cookie"
    assert rec.identity == "user-uuid-1234"
    assert rec.present is True


def test_inspect_notion_internal_api_missing(monkeypatch, tmp_path):
    _isolate_env(monkeypatch)
    _empty_firefox(monkeypatch, tmp_path)
    monkeypatch.setattr(connections, "_NOTION_TOKEN_FILE", str(tmp_path / "missing-token"))

    rec = inspect_notion_internal_api()
    _assert_full_record(rec)
    assert rec.source == "missing"
    assert rec.present is False


def test_inspect_notion_public_api_present(monkeypatch):
    _isolate_env(monkeypatch)
    monkeypatch.setenv("NOTION_TOKEN", "REDACTED-public-token")
    rec = inspect_notion_public_api()
    _assert_full_record(rec)
    assert rec.source == "env_var"
    assert rec.source_path == "$NOTION_TOKEN"
    assert rec.present is True


def test_inspect_notion_public_api_missing(monkeypatch):
    _isolate_env(monkeypatch)
    rec = inspect_notion_public_api()
    _assert_full_record(rec)
    assert rec.present is False
    assert rec.source == "missing"


def test_inspect_claude_projects_present(monkeypatch, tmp_path):
    _isolate_env(monkeypatch)
    profiles = tmp_path / "ff"
    profiles.mkdir()
    _firefox_with_cookies(profiles, ["sessionKey"], host="claude.ai")
    monkeypatch.setattr(connections, "_FIREFOX_COOKIES_GLOB", str(profiles / "*" / "cookies.sqlite"))

    rec = inspect_claude_projects()
    _assert_full_record(rec)
    assert rec.present is True
    assert rec.source == "firefox_cookie"


def test_inspect_claude_projects_missing(monkeypatch, tmp_path):
    _isolate_env(monkeypatch)
    _empty_firefox(monkeypatch, tmp_path)
    rec = inspect_claude_projects()
    _assert_full_record(rec)
    assert rec.present is False


def test_inspect_all_returns_three_records(monkeypatch, tmp_path):
    _isolate_env(monkeypatch)
    _empty_firefox(monkeypatch, tmp_path)
    monkeypatch.setattr(connections, "_NOTION_TOKEN_FILE", str(tmp_path / "missing-token"))
    records = inspect_all()
    assert len(records) == 3
    names = {r.name for r in records}
    assert names == {"notion_internal_api", "notion_public_api", "claude_projects"}
    for r in records:
        _assert_full_record(r)


def test_health_summary_shape_and_classification(monkeypatch, tmp_path):
    _isolate_env(monkeypatch)
    _empty_firefox(monkeypatch, tmp_path)
    monkeypatch.setattr(connections, "_NOTION_TOKEN_FILE", str(tmp_path / "missing-token"))
    monkeypatch.setenv("NOTION_TOKEN", "REDACTED")

    summary = health_summary()
    assert set(summary.keys()) == {"healthy", "stale", "missing", "records"}
    assert summary["healthy"] + summary["stale"] + summary["missing"] == 3
    assert summary["healthy"] >= 1
    assert summary["missing"] >= 1
    for r in summary["records"]:
        assert set(r.keys()) == _RECORD_FIELDS


def test_health_summary_marks_stale(monkeypatch, tmp_path):
    _isolate_env(monkeypatch)
    _empty_firefox(monkeypatch, tmp_path)
    token_file = tmp_path / "token-file"
    token_file.write_text("REDACTED\n")
    old = 1_000_000.0
    os.utime(token_file, (old, old))
    monkeypatch.setattr(connections, "_NOTION_TOKEN_FILE", str(token_file))

    summary = health_summary()
    assert summary["stale"] >= 1


def test_no_token_bytes_in_records(monkeypatch, tmp_path):
    _isolate_env(monkeypatch)
    monkeypatch.setenv("NOTION_TOKEN_V2", "v2-secret-bytes-XYZ")
    monkeypatch.setenv("NOTION_TOKEN", "ntn-secret-bytes-XYZ")
    _empty_firefox(monkeypatch, tmp_path)
    monkeypatch.setattr(connections, "_NOTION_TOKEN_FILE", str(tmp_path / "missing-token"))
    for r in inspect_all():
        blob = repr(r.to_dict())
        assert "v2-secret-bytes-XYZ" not in blob
        assert "ntn-secret-bytes-XYZ" not in blob
