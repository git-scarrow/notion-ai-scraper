"""Tests for _get_auth() cascade — specifically the freshness check that
prevents the token file from shadowing a rotated Firefox cookie."""
from __future__ import annotations

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mcp_server


@pytest.fixture(autouse=True)
def _reset_auth_state(monkeypatch):
    monkeypatch.setattr(mcp_server, "_auth_cache", None)
    monkeypatch.setattr(mcp_server, "_auth_cache_time", 0)
    monkeypatch.setattr(mcp_server, "_auth_db_mtime", 0)
    monkeypatch.setattr(mcp_server, "_AUTH_SOURCE", "none")
    monkeypatch.delenv("NOTION_TOKEN_V2", raising=False)
    monkeypatch.delenv("NOTION_USER_ID", raising=False)
    yield


def _seed_token_file(tmp_path, age_seconds: float, token: str = "FILE_TOK", user_id: str = "FILE_UID"):
    p = tmp_path / "token"
    p.write_text(f"{token}\n{user_id}\n")
    mtime = time.time() - age_seconds
    os.utime(p, (mtime, mtime))
    return p


def _seed_cookie_db(tmp_path, age_seconds: float):
    p = tmp_path / "cookies.sqlite"
    p.write_text("")
    mtime = time.time() - age_seconds
    os.utime(p, (mtime, mtime))
    return p


def test_file_used_when_fresher_than_firefox(tmp_path, monkeypatch):
    token_path = _seed_token_file(tmp_path, age_seconds=60)        # 1 min old
    cookie_path = _seed_cookie_db(tmp_path, age_seconds=86400)     # 1 day old
    monkeypatch.setattr(mcp_server, "_TOKEN_FILE", str(token_path))
    monkeypatch.setattr(mcp_server.cookie_extract, "get_firefox_cookies_db", lambda: str(cookie_path))

    def _should_not_run():
        raise AssertionError("Firefox extraction must not run when file is fresher")

    monkeypatch.setattr(mcp_server.cookie_extract, "get_auth", _should_not_run)

    token, uid = mcp_server._get_auth()
    assert (token, uid) == ("FILE_TOK", "FILE_UID")
    assert mcp_server._AUTH_SOURCE == "file"


def test_firefox_used_when_newer_than_file(tmp_path, monkeypatch):
    token_path = _seed_token_file(tmp_path, age_seconds=86400)     # 1 day old
    cookie_path = _seed_cookie_db(tmp_path, age_seconds=60)        # 1 min old
    monkeypatch.setattr(mcp_server, "_TOKEN_FILE", str(token_path))
    monkeypatch.setattr(mcp_server.cookie_extract, "get_firefox_cookies_db", lambda: str(cookie_path))
    monkeypatch.setattr(mcp_server.cookie_extract, "get_auth", lambda: ("FRESH_TOK", "FRESH_UID"))

    token, uid = mcp_server._get_auth()
    assert (token, uid) == ("FRESH_TOK", "FRESH_UID")
    assert mcp_server._AUTH_SOURCE == "firefox"
    assert token_path.read_text().splitlines()[0] == "FRESH_TOK"


def test_firefox_unreachable_falls_back_to_file(tmp_path, monkeypatch):
    token_path = _seed_token_file(tmp_path, age_seconds=86400)
    monkeypatch.setattr(mcp_server, "_TOKEN_FILE", str(token_path))

    def _no_db():
        raise FileNotFoundError("no cookies.sqlite")

    monkeypatch.setattr(mcp_server.cookie_extract, "get_firefox_cookies_db", _no_db)
    monkeypatch.setattr(mcp_server.cookie_extract, "get_auth", _no_db)

    token, uid = mcp_server._get_auth()
    assert (token, uid) == ("FILE_TOK", "FILE_UID")
    assert mcp_server._AUTH_SOURCE == "file"


def test_env_var_still_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTION_TOKEN_V2", "ENV_TOK")
    monkeypatch.setenv("NOTION_USER_ID", "ENV_UID")
    monkeypatch.setattr(mcp_server, "_TOKEN_FILE", str(tmp_path / "missing"))
    monkeypatch.setattr(mcp_server.cookie_extract, "get_firefox_cookies_db", lambda: (_ for _ in ()).throw(FileNotFoundError()))

    token, uid = mcp_server._get_auth()
    assert (token, uid) == ("ENV_TOK", "ENV_UID")
    assert mcp_server._AUTH_SOURCE == "env"
