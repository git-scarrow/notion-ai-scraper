# notion-forge

Firefox extension + Tampermonkey script + Python CLI + MCP server for capturing and managing Notion AI chat conversations and agent instructions.

## Environment

- Python venv: `cli/.venv` — use this for all CLI/MCP work; system Python lacks `mcp` and `pyyaml`
- Node: ES modules — use `node --input-type=module -e "import ..."` for inline scripts
- Workspace space_id: `f04bc8a1-18df-42d1-ba9f-961c491cdc1b` (constant)

## Testing

```bash
# Block builder round-trip (live data)
node --input-type=module -e "import {blocksToMarkdown,markdownToBlocks} from './agent-manager/block-builder.js'; ..."

# MCP server — FastMCP blocks on stdin, always pipe with timeout
printf 'JSON\nJSON\n' | timeout 30 cli/.venv/bin/python cli/mcp_server.py 2>/dev/null

# Fetch live Notion blocks
cli/.venv/bin/python -c "import sys; sys.path.insert(0,'cli'); import notion_client, cookie_extract; ..."
```

## MCP Server

- Entry: `cli/mcp_server.py`, registered in `.mcp.json`
- Server name: `notion-agents`
- Tools: `list_agents`, `list_workspace_agents`, `sync_registry`, `dump_agent`, `update_agent`, `publish_agent`, `discover_agent`, `register_agent`, `remove_agent`, `get_agent_tools`, `add_agent_mcp_server`, `remove_agent_mcp_server`, `set_agent_model`
- `sync_registry` auto-populates `cli/agents.yaml` from the live workspace (additive-only, safe to re-run)
- See `~/.agents/skills/notion-agent-mcp/SKILL.md` for full API reference

## Key files

| File | Purpose |
|---|---|
| `cli/mcp_server.py` | MCP server (13 tools) |
| `cli/notion_client.py` | Internal Notion API client |
| `cli/block_builder.py` | Markdown ↔ Notion blocks (Python) |
| `cli/cookie_extract.py` | Firefox `token_v2` auth |
| `cli/agents.yaml` | Agent registry (12 agents) |
| `agent-manager/block-builder.js` | Markdown ↔ Notion blocks (JS, used by extension) |
| `background/service-worker.js` | Extension: chat interception + agent write API |
| `popup/popup.js` | Extension: UI thin client |
| `.mcp.json` | MCP server registration |
