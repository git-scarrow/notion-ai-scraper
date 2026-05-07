# Integration: connection inspection MCP tools

`cli/connections.py` is self-contained. It exposes read-only auth records
(source, freshness, workspace, identity) without ever reading token bytes.

## Wiring into `cli/mcp_server.py`

Add one import and one call near the other MCP tool registrations.

```python
# near the top, with other local imports
from connections import register_connection_tools

# after `mcp = FastMCP("notion-agents")` and other tool blocks
register_connection_tools(mcp)
```

That registers two tools on the existing FastMCP server:

- `inspect_connections()` -> `list[dict]` — one record per auth surface
- `connection_health()` -> `{"healthy", "stale", "missing", "records"}`

## Why a separate module

- `_get_auth()` in `mcp_server.py` is a runtime cache; it mutates state and
  raises on missing auth. The inspector must never raise and never trigger
  Firefox extraction side-effects (cookie copy + token-file write).
- Keeps the security boundary explicit: `connections.py` is the only place
  that touches auth metadata, and it never touches token bytes.

## Verifying

```bash
cli/.venv/bin/python -m pytest cli/test_connections.py -v
cli/.venv/bin/python -c "from cli.connections import inspect_all; \
  [print(r.name, r.source, r.present) for r in inspect_all()]"
```
