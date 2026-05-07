# Integrating `tool_catalog.py` into mcp_server.py / dispatch_tools.py

`cli/tool_catalog.py` is self-contained and changes nothing on import. The
`TOOL_CATALOG` dict already covers ~30 existing tools with metadata, so even
without touching the registration sites the catalog is queryable.

To opt a tool into the catalog at registration time (and let metadata travel
with the function definition), swap `@mcp.tool()` for
`@register_tool_metadata(mcp, ...)`. With no extra kwargs the decorator is
exactly `mcp.tool()`.

## Two-line import change

```diff
--- a/cli/mcp_server.py
+++ b/cli/mcp_server.py
@@
 from mcp.server.fastmcp import FastMCP
+from tool_catalog import register_tool_metadata
```

```diff
--- a/cli/dispatch_tools.py
+++ b/cli/dispatch_tools.py
@@
 def register(mcp, cfg):
+    from tool_catalog import register_tool_metadata
```

## Per-tool decorator swap (examples)

```diff
-@mcp.tool()
-def count_database(database_id: str, filter: str = "", exact: bool = False) -> str:
+@register_tool_metadata(
+    mcp,
+    surface="notion_public_api", access="read", idempotent=True,
+    requires_space_id=False, safe_for_lab_query=True,
+    human_approval_required=False, expected_latency="medium",
+    canonical_read=True,
+)
+def count_database(database_id: str, filter: str = "", exact: bool = False) -> str:
```

```diff
-    @mcp.tool()
-    def handle_final_return(...):
+    @register_tool_metadata(
+        mcp,
+        surface="lab", access="write", idempotent=True,
+        requires_space_id=False, safe_for_lab_query=False,
+        human_approval_required=False, expected_latency="slow",
+        canonical_read=False,
+    )
+    def handle_final_return(...):
```

```diff
-@mcp.tool()
-def update_agent(agent_name, instructions_markdown=None, publish=True) -> str:
+@register_tool_metadata(
+    mcp,
+    surface="notion_internal_api", access="write", idempotent=False,
+    requires_space_id=False, safe_for_lab_query=False,
+    human_approval_required=True, expected_latency="medium",
+    canonical_read=False,
+)
+def update_agent(agent_name, instructions_markdown=None, publish=True) -> str:
```

The descriptor falls back to the function docstring's first line, so omitting
`description=...` is fine.

## Lab Query consumption

Once the Lab Query agent has access to a `tools_safe_for_lab_query()` view
(either via a new MCP tool or an embedded JSON dump at agent build time), it
should restrict its `lab_query` planner to that allowlist:

```python
from tool_catalog import tools_safe_for_lab_query
allowed = set(tools_safe_for_lab_query())
plan = [step for step in candidate_plan if step.tool in allowed]
```

This preserves the canonicality contract (no write-amplification, no slow
agent-chat round-trips) while still permitting `count_database`,
`describe_database`, `query_database`, `get_lab_topology`, and read-only
agent introspection.
