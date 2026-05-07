"""Tests for tool_catalog.py."""

import os
import sys
from dataclasses import fields

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tool_catalog
from tool_catalog import (
    TOOL_CATALOG,
    ToolMetadata,
    get_metadata,
    register_tool_metadata,
    tools_by_surface,
    tools_requiring_approval,
    tools_safe_for_lab_query,
)


def test_catalog_has_minimum_entries():
    assert len(TOOL_CATALOG) >= 20


def test_every_entry_has_all_required_fields():
    required = {f.name for f in fields(ToolMetadata)}
    for name, meta in TOOL_CATALOG.items():
        present = {f.name for f in fields(meta)}
        assert required <= present, f"{name} missing fields"
        assert meta.name == name
        assert meta.description, f"{name} has empty description"
        assert meta.surface in {
            "notion_public_api",
            "notion_internal_api",
            "lab",
            "claude_projects",
            "registry",
            "agent_chat",
            "writers_room",
        }
        assert meta.access in {"read", "write", "read_write"}
        assert meta.expected_latency in {"fast", "medium", "slow", "very_slow"}


def test_lab_query_safe_includes_read_only_public_api():
    safe = set(tools_safe_for_lab_query())
    assert "describe_database" in safe
    assert "query_database" in safe
    assert "count_database" in safe
    assert "get_lab_topology" in safe


def test_lab_query_safe_excludes_writes():
    safe = set(tools_safe_for_lab_query())
    assert "update_agent" not in safe
    assert "handle_final_return" not in safe
    assert "create_agent" not in safe
    assert "chat_with_agent" not in safe


def test_get_metadata_unknown_returns_none():
    assert get_metadata("does_not_exist") is None


def test_get_metadata_known_returns_entry():
    meta = get_metadata("count_database")
    assert meta is not None
    assert meta.surface == "notion_public_api"
    assert meta.canonical_read is True


def test_tools_by_surface_filters_correctly():
    lab_tools = set(tools_by_surface("lab"))
    assert "build_dispatch_packet" in lab_tools
    assert "handle_final_return" in lab_tools
    assert "describe_database" not in lab_tools

    public_api = set(tools_by_surface("notion_public_api"))
    assert public_api == {"describe_database", "query_database", "count_database"}

    assert tools_by_surface("nonexistent_surface") == []


def test_tools_requiring_approval_includes_destructive_writes():
    approval = set(tools_requiring_approval())
    assert "restore_agent_instruction_version" in approval
    assert "update_agent" in approval
    assert "create_agent" in approval
    assert "describe_database" not in approval


def test_register_tool_metadata_no_kwargs_is_passthrough():
    calls: list = []

    class FakeMCP:
        def tool(self):
            def decorator(fn):
                calls.append(fn.__name__)
                return fn
            return decorator

    @register_tool_metadata(FakeMCP())
    def some_tool():
        """Does a thing."""
        return 1

    assert calls == ["some_tool"]
    assert some_tool() == 1


def test_register_tool_metadata_with_kwargs_records_metadata():
    class FakeMCP:
        def tool(self):
            def decorator(fn):
                return fn
            return decorator

    snapshot = dict(TOOL_CATALOG)
    try:
        @register_tool_metadata(
            FakeMCP(),
            surface="lab",
            access="read",
            idempotent=True,
            requires_space_id=False,
            safe_for_lab_query=True,
            human_approval_required=False,
            expected_latency="fast",
            canonical_read=True,
        )
        def _ephemeral_tool():
            """Ephemeral test tool."""
            return "ok"

        meta = get_metadata("_ephemeral_tool")
        assert meta is not None
        assert meta.surface == "lab"
        assert meta.description == "Ephemeral test tool."
        assert _ephemeral_tool() == "ok"
    finally:
        TOOL_CATALOG.clear()
        TOOL_CATALOG.update(snapshot)
