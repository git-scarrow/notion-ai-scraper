# notion-forge

Firefox extension + Tampermonkey script + Python CLI + MCP server for capturing and managing Notion AI conversations, custom Notion agents, Notion-backed Lab workflows, and Claude.ai Projects.

## Environment

- Python venv: `cli/.venv` — use this for all CLI/MCP work; system Python lacks `mcp` and `pyyaml`
- Node: ES modules — use `node --input-type=module -e "import ..."` for inline scripts

## Configuration
The project uses a centralized configuration pattern in `cli/config.py`. All hardcoded IDs are stored there as defaults and can be overridden via environment variables or a `.env` file in the project root.

### Core Environment Variables
- `NOTION_TOKEN`: Notion integration token (required for public API tools like `lab_auditor.py`).
- `NOTION_SPACE_ID`: The target Notion Space UUID.
- `WORK_ITEMS_DB_ID`: The Work Items database UUID.
- `LAB_PROJECTS_DB_ID`: The Lab Projects database UUID.
- `AUDIT_LOG_DB_ID`: The Lab Audit Log database UUID.
- `EVIDENCE_DOSSIER_DB_ID`: The Evidence Dossier database UUID (Writing Workshop).

### Tool-Specific Configuration
- `LIBRARIAN_WORKFLOW_ID`: The Agent workflow ID for the Lab Librarian.
- `LIBRARIAN_BOT_RUNTIME`: The Bot ID for the Librarian's runtime permission.
- `LIBRARIAN_BOT_DRAFT`: The Bot ID for the Librarian's draft permission.

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
- Tools include agent registry/config/publish operations, agent chat polling, database describe/query/count operations, Lab dispatch/return tools, scene dispatch, and Claude Project sync tools. Use the MCP tool list as the live source of truth when signatures matter.
- `describe_database(database_id)` returns the schema (property names, types, select/status options). **Always call this before `query_database` if you don't know the exact property names and types.** The filter type key in `query_database` must match the property's actual type (e.g. `status` not `select` for status-type properties). `query_database` auto-corrects common mismatches, but `describe_database` prevents them entirely.
- For exact counts, use `count_database(..., exact=True)` or Lab Query. Do not infer totals from a limited `query_database` page, view, or search result.
- `chat_with_agent(agent_name, message, wait=True)` sends a message and returns a JSON status envelope with `thread_id`, `message_id`, `content`, and follow-up tracking handles. Its blocking wait is capped to a transport-safe budget, so long-running agents return `status:"pending"` before the MCP tool call itself times out.
- `start_agent_run(agent_name, message, new_thread=True)` is the preferred entry point for slow agents. It dispatches immediately and returns queued status plus the same tracking handles you can pass to `check_agent_response`.
- `create_agent(name, space_id)` creates a new agent programmatically (workflow + instruction page + sidebar + initial publish).
- `update_agent` auto-grants `reader` access for any `{{page:uuid}}` mentions in instructions before publish. Pre-publish validation warns on unresolvable pages.
- `sync_registry` auto-populates `cli/agents.yaml` from the live workspace (additive-only, safe to re-run). Also syncs to `agent-env/template-data.json` for skill rendering.
- See `~/.agents/skills/notion-agent-mcp/SKILL.md` for full API reference

## Lab Query

- `lab_query` is the preferred compressed read surface for broad Notion questions. Treat it like an Exa-style query agent for the Lab workspace: ask a natural-language question and get a compact answer without loading large database JSON into context.
- Live model: MiniMax M2.5 (`fireworks-minimax-m2.5`).
- Canonicality contract: compressed answers must preserve the answer set. Counts and distributions must state scope (`exact total`, `matched count`, `scanned count`, or `limit`) and must not call a view/search subset a database total.
- Known-good smoke check: `chat_with_agent(lab_query, "In Work Items, how many total rows are there, and how many have Status = Dispatch Ready? Use exact counts. Return one sentence only.", new_thread=True, wait=True)` should return `Work Items: 581 total; Dispatch Ready: 22.`
- Live configuration should show `Lab Control Plane (Notion API)` with `Enabled: 22/22 tools`, including `API-query-data-source`, `API-retrieve-a-data-source`, and `API-retrieve-a-database`.

## Dispatch Returns

- `handle_final_return` is the normal execution-plane return path. It validates return payloads, checks idempotency by `run_id`, maps verdicts to Work Item status/verdict, stamps `Return Received At` and `Return Consumed At`, appends result blocks, and writes an audit entry.
- `Return Received At` is the Intake Clerk trigger and the structural boundary for "returned but still In Progress" lag windows.
- `direct_closeout_return` is the fallback closeout path when no GitHub issue, dispatch packet, or trusted `run_id` is available. It generates an idempotency key if needed and writes through the same direct Notion API return ingestion path.
- `github_return.py` now moves GitHub closeout to `Awaiting Intake` and tags the audit transition by evidence quality, e.g. `InProgress→Awaiting Intake [evidence:close_state_only]`.

## ID Duality & Tool Compatibility

Notion databases have two distinct UUIDs. Using the wrong one will result in a 404.

| ID Type | Example Name | Tooling |
|---|---|---|
| **notion_public_id** | `page_id` | Public API (`retrieve-a-database`, `query-database`, `update-page-v2`) |
| **notion_internal_id** | `collection_id` | Internal Tools (`triggers`, `query-data-source`, `view`) |

## Dashboard Server

- Entry: `cli/dashboard_server.py`, runs on port 8099 by default
- Start: `cli/.venv/bin/python cli/dashboard_server.py [--port 8099]`
- Frontend: `dashboard/` (plain HTML + ES modules, Observable Plot via CDN — no build step)
- Uses `notion_api.NotionAPIClient` directly (public API, `NOTION_TOKEN`)
- Databases shown: Work Items, Lab Projects, Audit Log (from `cli/config.py`)
- Routes: `GET /` (HTML), `/api/databases`, `/api/schema/{db_id}`, `/api/query/{db_id}`, `/api/aggregate/{db_id}`
- `aggregate` mode fetches all pages and returns per-column statistics (mirrors `_aggregate_pages` in mcp_server.py)
- `query_database` in mcp_server.py gained `aggregate`, `sample`, and `max_tokens` modes in the feature/notion-dashboard merge

## Key files

| File | Purpose |
|---|---|
| `cli/mcp_server.py` | MCP server for Notion agents, databases, dispatch, and Claude Project sync |
| `cli/dashboard_server.py` | HTTP dashboard server (Starlette + uvicorn, port 8099) |
| `dashboard/index.html` | Dashboard shell |
| `dashboard/app.js` | Chart rendering (Observable Plot CDN, ES modules) |
| `dashboard/dashboard.css` | Dark theme styles |
| `cli/notion_client.py` | Internal Notion API client |
| `cli/block_builder.py` | Markdown ↔ Notion blocks (Python) |
| `cli/cookie_extract.py` | Firefox `token_v2` auth |
| `cli/agents.yaml` | Agent registry (12 agents) |
| `agent-manager/block-builder.js` | Markdown ↔ Notion blocks (JS, used by extension) |
| `background/service-worker.js` | Extension: chat interception + agent write API |
| `popup/popup.js` | Extension: UI thin client |
| `cli/dispatch.py` | Dispatch adapter (v1.1 contract) |
| `cli/dispatch_tools.py` | Lab dispatch/return MCP tool registration |
| `cli/contracts/` | JSON schemas + configs for dispatch contract |
| `cli/test_dispatch.py` | Dispatch adapter unit tests |
| `cli/agent_instructions/evidence_verifier.md` | Evidence Verifier agent instructions (source of truth) |
| `cli/claude_cli.py` | Claude.ai Project sync CLI |
| `cli/claude_client.py` | Claude.ai Projects API client (internal web API) |
| `cli/claude_cookie_extract.py` | Firefox cookie extraction for Claude.ai auth |
| `.mcp.json` | MCP server registration |
