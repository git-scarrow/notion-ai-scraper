"""
tool_catalog.py — Typed metadata catalog for notion-forge MCP tools.

Augments the flat `@mcp.tool()` registration surface with per-tool metadata
(surface, access mode, idempotency, latency, Lab Query safety, etc.) so that
callers like the Lab Query agent, dispatch pre-flight checks, and approval
gates can reason about tools without grepping docstrings.

Self-contained: importing this module does not modify FastMCP state. Use
`register_tool_metadata(mcp, ...)` as a drop-in for `@mcp.tool()` to opt a
tool into the catalog at registration time. Tools defined here without a
runtime decorator wrapping are still queryable from TOOL_CATALOG.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Callable, Literal


Surface = Literal[
    "notion_public_api",
    "notion_internal_api",
    "lab",
    "claude_projects",
    "registry",
    "agent_chat",
    "writers_room",
]
Access = Literal["read", "write", "read_write"]
Latency = Literal["fast", "medium", "slow", "very_slow"]


@dataclass(frozen=True)
class ToolMetadata:
    name: str
    surface: Surface
    access: Access
    idempotent: bool
    requires_space_id: bool
    safe_for_lab_query: bool
    human_approval_required: bool
    expected_latency: Latency
    canonical_read: bool
    description: str


def _md(**kwargs) -> ToolMetadata:
    return ToolMetadata(**kwargs)


_RAW: list[ToolMetadata] = [
    _md(
        name="list_agents",
        surface="registry",
        access="read",
        idempotent=True,
        requires_space_id=False,
        safe_for_lab_query=True,
        human_approval_required=False,
        expected_latency="fast",
        canonical_read=True,
        description="List registered Notion AI agents from agents.yaml or live workspace.",
    ),
    _md(
        name="sync_registry",
        surface="registry",
        access="write",
        idempotent=True,
        requires_space_id=False,
        safe_for_lab_query=False,
        human_approval_required=False,
        expected_latency="medium",
        canonical_read=False,
        description="Refresh agents.yaml from the live workspace (additive only).",
    ),
    _md(
        name="dump_agent",
        surface="notion_internal_api",
        access="read",
        idempotent=True,
        requires_space_id=False,
        safe_for_lab_query=True,
        human_approval_required=False,
        expected_latency="fast",
        canonical_read=True,
        description="Fetch live instructions of an agent as Markdown.",
    ),
    _md(
        name="list_agent_instruction_versions",
        surface="notion_internal_api",
        access="read",
        idempotent=True,
        requires_space_id=False,
        safe_for_lab_query=True,
        human_approval_required=False,
        expected_latency="fast",
        canonical_read=True,
        description="List historical snapshots of an agent's instruction page.",
    ),
    _md(
        name="get_agent_instruction_version",
        surface="notion_internal_api",
        access="read",
        idempotent=True,
        requires_space_id=False,
        safe_for_lab_query=True,
        human_approval_required=False,
        expected_latency="fast",
        canonical_read=True,
        description="Fetch a specific historical instruction snapshot.",
    ),
    _md(
        name="restore_agent_instruction_version",
        surface="notion_internal_api",
        access="write",
        idempotent=False,
        requires_space_id=False,
        safe_for_lab_query=False,
        human_approval_required=True,
        expected_latency="medium",
        canonical_read=False,
        description="Destructively restore an agent's instructions to a prior snapshot.",
    ),
    _md(
        name="update_agent",
        surface="notion_internal_api",
        access="write",
        idempotent=False,
        requires_space_id=False,
        safe_for_lab_query=False,
        human_approval_required=True,
        expected_latency="medium",
        canonical_read=False,
        description="Replace agent instructions and publish.",
    ),
    _md(
        name="update_agent_from_file",
        surface="notion_internal_api",
        access="write",
        idempotent=False,
        requires_space_id=False,
        safe_for_lab_query=False,
        human_approval_required=True,
        expected_latency="medium",
        canonical_read=False,
        description="Replace agent instructions from a local Markdown file.",
    ),
    _md(
        name="discover_agent",
        surface="notion_internal_api",
        access="read",
        idempotent=True,
        requires_space_id=False,
        safe_for_lab_query=True,
        human_approval_required=False,
        expected_latency="fast",
        canonical_read=True,
        description="Resolve agent metadata from a workflow URL or UUID.",
    ),
    _md(
        name="manage_registry",
        surface="registry",
        access="write",
        idempotent=False,
        requires_space_id=False,
        safe_for_lab_query=False,
        human_approval_required=False,
        expected_latency="fast",
        canonical_read=False,
        description="Register or remove an agent in agents.yaml.",
    ),
    _md(
        name="get_conversation",
        surface="agent_chat",
        access="read",
        idempotent=True,
        requires_space_id=False,
        safe_for_lab_query=True,
        human_approval_required=False,
        expected_latency="medium",
        canonical_read=True,
        description="Fetch a Notion AI conversation transcript.",
    ),
    _md(
        name="check_agent_response",
        surface="agent_chat",
        access="read",
        idempotent=True,
        requires_space_id=False,
        safe_for_lab_query=True,
        human_approval_required=False,
        expected_latency="medium",
        canonical_read=True,
        description="Non-blocking poll for the latest assistant turn after a sent message.",
    ),
    _md(
        name="chat_with_agent",
        surface="agent_chat",
        access="read_write",
        idempotent=False,
        requires_space_id=False,
        safe_for_lab_query=False,
        human_approval_required=False,
        expected_latency="very_slow",
        canonical_read=False,
        description="Send a message to a Notion AI agent and optionally wait for a response.",
    ),
    _md(
        name="start_agent_run",
        surface="agent_chat",
        access="write",
        idempotent=False,
        requires_space_id=False,
        safe_for_lab_query=False,
        human_approval_required=False,
        expected_latency="fast",
        canonical_read=False,
        description="Non-blocking dispatch to an agent; returns tracking handles.",
    ),
    _md(
        name="get_triggers",
        surface="notion_internal_api",
        access="read",
        idempotent=True,
        requires_space_id=False,
        safe_for_lab_query=True,
        human_approval_required=False,
        expected_latency="fast",
        canonical_read=True,
        description="Show agent or database trigger configuration.",
    ),
    _md(
        name="get_lab_topology",
        surface="lab",
        access="read",
        idempotent=True,
        requires_space_id=False,
        safe_for_lab_query=True,
        human_approval_required=False,
        expected_latency="medium",
        canonical_read=True,
        description="Compile and return the live Lab topology summary.",
    ),
    _md(
        name="describe_database",
        surface="notion_public_api",
        access="read",
        idempotent=True,
        requires_space_id=False,
        safe_for_lab_query=True,
        human_approval_required=False,
        expected_latency="fast",
        canonical_read=True,
        description="Show a database's schema: properties, types, and select options.",
    ),
    _md(
        name="query_database",
        surface="notion_public_api",
        access="read",
        idempotent=True,
        requires_space_id=False,
        safe_for_lab_query=True,
        human_approval_required=False,
        expected_latency="medium",
        canonical_read=False,
        description="Query a Notion database; pages or aggregates rows.",
    ),
    _md(
        name="count_database",
        surface="notion_public_api",
        access="read",
        idempotent=True,
        requires_space_id=False,
        safe_for_lab_query=True,
        human_approval_required=False,
        expected_latency="medium",
        canonical_read=True,
        description="Count rows in a Notion database with optional filter.",
    ),
    _md(
        name="configure_agent_mcp",
        surface="notion_internal_api",
        access="write",
        idempotent=False,
        requires_space_id=False,
        safe_for_lab_query=False,
        human_approval_required=True,
        expected_latency="medium",
        canonical_read=False,
        description="Add or remove an MCP server from an agent's tool config.",
    ),
    _md(
        name="set_agent_model",
        surface="notion_internal_api",
        access="write",
        idempotent=True,
        requires_space_id=False,
        safe_for_lab_query=False,
        human_approval_required=True,
        expected_latency="medium",
        canonical_read=False,
        description="Change a Notion AI agent's underlying model.",
    ),
    _md(
        name="create_agent",
        surface="notion_internal_api",
        access="write",
        idempotent=False,
        requires_space_id=True,
        safe_for_lab_query=False,
        human_approval_required=True,
        expected_latency="slow",
        canonical_read=False,
        description="Create a new Notion AI Agent from scratch.",
    ),
    _md(
        name="get_agent_config_raw",
        surface="notion_internal_api",
        access="read",
        idempotent=True,
        requires_space_id=False,
        safe_for_lab_query=True,
        human_approval_required=False,
        expected_latency="fast",
        canonical_read=True,
        description="Fetch the raw workflow record for an agent.",
    ),
    _md(
        name="set_agent_config_raw",
        surface="notion_internal_api",
        access="write",
        idempotent=False,
        requires_space_id=False,
        safe_for_lab_query=False,
        human_approval_required=True,
        expected_latency="medium",
        canonical_read=False,
        description="Update an agent's configuration in bulk from raw JSON.",
    ),
    _md(
        name="grant_resource_access",
        surface="notion_internal_api",
        access="write",
        idempotent=True,
        requires_space_id=False,
        safe_for_lab_query=False,
        human_approval_required=True,
        expected_latency="medium",
        canonical_read=False,
        description="Grant an agent reader/editor access to a Notion page or database.",
    ),
    _md(
        name="check_gates",
        surface="lab",
        access="read",
        idempotent=True,
        requires_space_id=False,
        safe_for_lab_query=True,
        human_approval_required=False,
        expected_latency="fast",
        canonical_read=True,
        description="Check Pre-Flight and Cascade Depth gates before performing writes.",
    ),
    _md(
        name="get_dispatchable_items",
        surface="lab",
        access="read",
        idempotent=True,
        requires_space_id=False,
        safe_for_lab_query=True,
        human_approval_required=False,
        expected_latency="medium",
        canonical_read=True,
        description="Find Work Items ready for dispatch by an execution plane.",
    ),
    _md(
        name="build_dispatch_packet",
        surface="lab",
        access="read",
        idempotent=True,
        requires_space_id=False,
        safe_for_lab_query=False,
        human_approval_required=False,
        expected_latency="medium",
        canonical_read=False,
        description="Build and validate a dispatch packet for a Work Item.",
    ),
    _md(
        name="stamp_dispatch_consumed",
        surface="lab",
        access="write",
        idempotent=True,
        requires_space_id=False,
        safe_for_lab_query=False,
        human_approval_required=False,
        expected_latency="medium",
        canonical_read=False,
        description="Mark a Work Item as accepted by an execution plane (run_id-keyed).",
    ),
    _md(
        name="fail_dispatch_preflight",
        surface="lab",
        access="write",
        idempotent=True,
        requires_space_id=False,
        safe_for_lab_query=False,
        human_approval_required=False,
        expected_latency="medium",
        canonical_read=False,
        description="Record a dispatch preflight failure and restore item state.",
    ),
    _md(
        name="handle_final_return",
        surface="lab",
        access="write",
        idempotent=True,
        requires_space_id=False,
        safe_for_lab_query=False,
        human_approval_required=False,
        expected_latency="slow",
        canonical_read=False,
        description="Ingest a final return payload from an execution plane (run_id-keyed).",
    ),
    _md(
        name="direct_closeout_return",
        surface="lab",
        access="write",
        idempotent=True,
        requires_space_id=False,
        safe_for_lab_query=False,
        human_approval_required=False,
        expected_latency="slow",
        canonical_read=False,
        description="Fallback closeout path when no GitHub Issue or trusted run_id exists.",
    ),
    _md(
        name="dispatch_scene",
        surface="writers_room",
        access="write",
        idempotent=False,
        requires_space_id=False,
        safe_for_lab_query=False,
        human_approval_required=False,
        expected_latency="medium",
        canonical_read=False,
        description="Create a Scene Item and fire the writers-room entry signal.",
    ),
]


_REQUIRED_FIELDS = {f.name for f in fields(ToolMetadata)}


def _validate(entries: list[ToolMetadata]) -> dict[str, ToolMetadata]:
    seen: dict[str, ToolMetadata] = {}
    for entry in entries:
        missing = _REQUIRED_FIELDS - {f.name for f in fields(entry) if getattr(entry, f.name) is not None or f.name in {"idempotent", "requires_space_id", "safe_for_lab_query", "human_approval_required", "canonical_read"}}
        if missing:
            raise ValueError(f"ToolMetadata for {entry.name!r} missing fields: {missing}")
        if entry.name in seen:
            raise ValueError(f"Duplicate ToolMetadata entry for {entry.name!r}")
        seen[entry.name] = entry
    return seen


TOOL_CATALOG: dict[str, ToolMetadata] = _validate(_RAW)


def get_metadata(tool_name: str) -> ToolMetadata | None:
    return TOOL_CATALOG.get(tool_name)


def tools_safe_for_lab_query() -> list[str]:
    return sorted(name for name, m in TOOL_CATALOG.items() if m.safe_for_lab_query)


def tools_by_surface(surface: str) -> list[str]:
    return sorted(name for name, m in TOOL_CATALOG.items() if m.surface == surface)


def tools_requiring_approval() -> list[str]:
    return sorted(name for name, m in TOOL_CATALOG.items() if m.human_approval_required)


SCOPE_LABELS: tuple[str, ...] = (
    "exact total",
    "matched count",
    "scanned count",
    "limit",
)


def lab_query_catalog_payload() -> dict[str, list[str]]:
    return {
        "safe_for_lab_query": tools_safe_for_lab_query(),
        "canonical_reads": sorted(
            name for name, m in TOOL_CATALOG.items() if m.canonical_read
        ),
        "requires_approval": tools_requiring_approval(),
        "scope_labels": list(SCOPE_LABELS),
    }


def register_lab_query_tools(mcp) -> None:
    """Register the Lab Query tool-allowlist discovery tool on an MCP server."""
    import json as _json

    @mcp.tool()
    def lab_query_tool_catalog() -> str:
        """Return the Lab Query tool allowlist and canonicality scope labels.

        Output JSON keys:
          safe_for_lab_query: tools the Lab Query agent may call.
          canonical_reads: tools whose results may back a committed answer.
          requires_approval: tools gated behind human approval (never call).
          scope_labels: required scope labels for any count/distribution answer.
        """
        return _json.dumps(lab_query_catalog_payload(), indent=2, sort_keys=True)


def register_tool_metadata(mcp, **metadata_kwargs) -> Callable:
    """Drop-in replacement for `@mcp.tool()` that also records metadata.

    Usage:
        @register_tool_metadata(mcp, surface="lab", access="read", ...)
        def my_tool(...): ...

    With no metadata kwargs, behaves exactly like `@mcp.tool()`.
    """
    base_decorator = mcp.tool()

    if not metadata_kwargs:
        return base_decorator

    def decorator(fn: Callable) -> Callable:
        name = metadata_kwargs.pop("name", fn.__name__)
        description = metadata_kwargs.pop(
            "description",
            (fn.__doc__ or "").strip().splitlines()[0] if fn.__doc__ else fn.__name__,
        )
        meta = ToolMetadata(name=name, description=description, **metadata_kwargs)
        TOOL_CATALOG[name] = meta
        return base_decorator(fn)

    return decorator
