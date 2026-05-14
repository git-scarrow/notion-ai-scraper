# Notion Platform Migration Audit

Date: 2026-05-14

This is an audit-only migration plan for adapting Notion Forge to Notion's May
13, 2026 Developer Platform release. It does not change runtime behavior. The
goal is to decide what should stay local, what should move to official Notion
surfaces, and what should remain behind private/internal API boundaries until
Notion exposes an official replacement.

## Platform Baseline

Primary Notion surfaces considered:

- [3.5: Notion Developer Platform](https://www.notion.com/releases/2026-05-13)
  announces Workers, database syncs, agent tools, webhook triggers, Notion CLI,
  Notion MCP improvements, External Agents API alpha, and Agent SDK alpha.
- [Notion Workers](https://developers.notion.com/workers/get-started/overview)
  are hosted TypeScript programs deployed with `ntn workers deploy`. A Worker
  can register syncs, agent tools, and webhooks.
- [Worker agent tools](https://developers.notion.com/workers/guides/tools) are
  deterministic functions exposed to Notion Custom Agents with stable tool keys,
  JSON schemas, optional structured output schemas, and read-only hints.
- [Official Notion MCP](https://developers.notion.com/guides/mcp/get-started-with-mcp)
  is available at `https://mcp.notion.com/mcp`, but the documented client flows
  require OAuth login. Treat it as a strong replacement for interactive,
  user-authenticated clients, not as the only backend for headless automation.

## Migration Decisions

Use these decision labels throughout the audit:

| Decision | Meaning |
| --- | --- |
| `keep_local` | Notion Forge remains the source of truth because the behavior is Lab-specific, cross-system, or contract-heavy. |
| `replace_with_official_mcp_or_api` | Prefer official Notion MCP/API once output shape and auth model are validated. Keep the local tool as a compatibility wrapper until callers move. |
| `worker_candidate` | Candidate for a Notion Worker tool/webhook, with the existing local path kept as fallback during migration. |
| `internal_api_hold` | Uses private Notion API, `token_v2`, workflow records, or private agent-chat endpoints. Keep isolated until official support covers the same behavior. |
| `retire_or_defer` | Do not expand. Retire only when an official feature fully replaces the user-facing need. |

## Component Inventory

| Surface | Current role | Decision | Notes |
| --- | --- | --- | --- |
| Lab dispatch and return contracts | Gates, dispatch packets, run acceptance, final returns, direct closeout, status/verdict mapping, audit log writes | `keep_local` | These encode Sam's Lab semantics, not generic Notion behavior. Workers can shadow small tools later, but they must not become authoritative until idempotency and audit behavior match. |
| Generic database read/query/count tools | Describe/query/count Notion databases through local public API wrappers | `replace_with_official_mcp_or_api` | Official MCP/API should become the preferred read surface for interactive clients. Keep local wrappers where exact count behavior, aggregation, or headless service tokens are needed. |
| Custom Notion agent config and publishing | Read/write workflow-parented instruction pages, model config, MCP modules, page grants, publish versions | `internal_api_hold` | Current behavior depends on private `workflow` records and `publishCustomAgentVersion`. No replacement is assumed until official APIs can read/write and publish custom agent definitions. |
| Notion agent chat and transcript access | Start/check agent runs and capture private conversation transcripts | `internal_api_hold` | Watch External Agents API and Agent SDK alpha, but do not depend on them until available and contract-compatible. |
| Browser extension and Tampermonkey capture | Capture live/historical Notion AI chats from private endpoints | `retire_or_defer` | Keep maintenance-only. Retire only if official export/Markdown/Agent SDK surfaces cover the same transcript fidelity. |
| Claude Project sync | Manage Claude.ai Project docs, instructions, and chats | `keep_local` | Out of scope for Notion's platform. Preserve as a separate integration surface. |
| Local dashboard | Inspect and aggregate Lab databases | `keep_local` | Useful operator view. It may swap read backends later, but the dashboard itself remains a Notion Forge surface. |
| Webhook relays | GitHub/Notion webhook intake and dispatch-poller signaling | `worker_candidate` | A later lane should test Worker webhooks for inbound events. Preserve current receiver until deployed Workers prove parity. |

## Tool Catalog Matrix

This matrix covers every entry in `TOOL_CATALOG` as of this audit.

| Tool | Current surface | Decision | Official target | Blocking gap / fallback |
| --- | --- | --- | --- | --- |
| `build_dispatch_packet` | `lab` read | `keep_local` | None for authority; possible Worker shadow later | Must preserve V1-V22 gates, packet schema, project inheritance, and execution-plane expectations. |
| `chat_with_agent` | `agent_chat` read/write | `internal_api_hold` | Agent SDK / External Agents API watchlist | Current path sends Notion AI agent messages through private endpoints. Keep local fallback. |
| `check_agent_response` | `agent_chat` read | `internal_api_hold` | Agent SDK / External Agents API watchlist | Polling semantics and thread handles are private. |
| `check_gates` | `lab` read | `worker_candidate` | Worker agent tool | Good first Worker candidate. Must return the same halt/proceed shape and preserve Pre-Flight and Cascade Depth checks. |
| `configure_agent_mcp` | `notion_internal_api` write | `internal_api_hold` | None yet | Current mutator path is fragile; prefer full live module rewrite locally until official custom-agent config APIs exist. |
| `count_database` | `notion_public_api` read | `replace_with_official_mcp_or_api` | Official Notion MCP/API | Preserve exact-count contract and scope labels before migrating callers. |
| `create_agent` | `notion_internal_api` write | `internal_api_hold` | None yet | Requires workflow creation and instruction-page wiring not covered by public API. |
| `describe_database` | `notion_public_api` read | `replace_with_official_mcp_or_api` | Official Notion MCP/API | Keep local compatibility until callers no longer depend on current schema formatting. |
| `direct_closeout_return` | `lab` write | `keep_local` | None for authority | Must preserve generated idempotency key, body append, return stamps, status mapping, and Intake trigger. |
| `discover_agent` | `notion_internal_api` read | `internal_api_hold` | None yet | Depends on workflow IDs and private records. |
| `dispatch_scene` | `writers_room` write | `worker_candidate` | Worker agent tool | Candidate after Lab gate tools. Must preserve scene schema, entry-signal timestamp, and parent Work Item behavior. |
| `dump_agent` | `notion_internal_api` read | `internal_api_hold` | None yet | Reads workflow-parented instruction pages. |
| `fail_dispatch_preflight` | `lab` write | `keep_local` | None for authority | Must preserve conflict handling and state restoration. |
| `get_agent_config_raw` | `notion_internal_api` read | `internal_api_hold` | None yet | Raw workflow records are private. |
| `get_agent_instruction_version` | `notion_internal_api` read | `internal_api_hold` | None yet | Version source is private/internal. |
| `get_conversation` | `agent_chat` read | `internal_api_hold` | Agent SDK / External Agents API watchlist | Keep until official transcript access matches fidelity. |
| `get_dispatchable_items` | `lab` read | `worker_candidate` | Worker agent tool or official MCP/API-backed read | Candidate as dispatch status helper. Must preserve selection criteria and table output semantics. |
| `get_lab_topology` | `lab` read | `worker_candidate` | Worker agent tool or official MCP/API-backed read | Candidate for a read-only topology/status tool if output stays compact and canonical. |
| `get_triggers` | `notion_internal_api` read | `internal_api_hold` | None yet | Current trigger reads depend on internal IDs/records. |
| `grant_resource_access` | `notion_internal_api` write | `internal_api_hold` | None yet | Custom-agent resource grants are private workflow-module config. |
| `handle_final_return` | `lab` write | `keep_local` | None for authority | Must preserve run_id idempotency, redaction/truncation, return stamps, audit log, status/verdict mapping, and webhook parity. |
| `list_agent_instruction_versions` | `notion_internal_api` read | `internal_api_hold` | None yet | Instruction version history is not public. |
| `list_agents` | `registry` read | `keep_local` | Possible official agent directory later | Local registry remains useful. Live workspace mode still depends on private records and should stay isolated. |
| `manage_registry` | `registry` write | `keep_local` | None | Local YAML registry management remains a local control-plane function. |
| `query_database` | `notion_public_api` read | `replace_with_official_mcp_or_api` | Official Notion MCP/API | Preserve aggregate/sample/max-token modes or keep local wrapper for those behaviors. |
| `restore_agent_instruction_version` | `notion_internal_api` write | `internal_api_hold` | None yet | Destructive internal write; keep human approval and local path only. |
| `set_agent_config_raw` | `notion_internal_api` write | `internal_api_hold` | None yet | Bulk raw config updates are private and should remain paused unless explicitly re-enabled. |
| `set_agent_model` | `notion_internal_api` write | `internal_api_hold` | None yet | Model config is private workflow state. |
| `stamp_dispatch_consumed` | `lab` write | `keep_local` | None for authority | Must preserve race guards, run_id ownership, status transition, and audit write. |
| `start_agent_run` | `agent_chat` write | `internal_api_hold` | Agent SDK / External Agents API watchlist | Current non-blocking dispatch uses private chat endpoints. |
| `sync_registry` | `registry` write | `internal_api_hold` | Possible official agent directory later | Writes local registry and agent-env template data from private workspace reads. Keep isolated. |
| `update_agent` | `notion_internal_api` write | `internal_api_hold` | None yet | Replaces workflow-parented instructions and publishes through private API. |
| `update_agent_from_file` | `notion_internal_api` write | `internal_api_hold` | None yet | Same as `update_agent`, with file-based payload transport. |

## Lab Tools First Lane

The first implementation lane after this audit should be a Worker proof of
concept for read-only, deterministic Lab tools. Do not migrate authoritative
write paths first.

> **Correction (2026-05-14):** The original framing called this a "migration"
> or "swap" of agent tools. That was inaccurate. A live state inspection
> showed **no Notion Custom Agent in this workspace has the local
> `notion-agents` MCP server attached**, so the `check_gates`-style prose in
> agent instructions is doctrinal only — no agent has been calling those
> tools. The actual Lane 1 work is therefore **first-time attach of a
> Notion-native deterministic capability**, not a swap. Adoption (attaching a
> deployed Worker tool to a specific agent) is a separate step that requires
> the Notion agent-settings UI ("Add connection") — neither the `ntn` CLI nor
> the `notion-agents` MCP server exposes a programmatic per-agent attach
> endpoint as of 2026-05-14.

Recommended order:

1. `check_gates`: Worker tool returns the same JSON halt/proceed contract as the
   current MCP tool. **(Lane 1 complete: deployed, parity verified — see
   below.)**
2. `get_dispatchable_items`: Worker tool returns a structured array plus a
   concise display string, matching current selection criteria.
3. `get_lab_topology`: Worker tool returns the same compact topology summary
   used by agents, backed by official Notion reads where possible.
4. `dispatch_scene`: evaluate separately because it writes and stamps an entry
   signal. Treat it as second-wave even though it is a Worker candidate.

Lane 1 acceptance gates (for `check_gates`):

- ✅ local MCP smoke and Worker smoke for the same fixture/live item
  (`cli/check_gates_parity.py` covers both, including `--remote`);
- ✅ output-shape comparison preserves every field;
- ✅ documented fallback (local MCP `check_gates` unchanged in `cli/dispatch.py`
  and `cli/dispatch_tools.py`);
- ✅ rollback procedure (see below) for removing the Worker tool from an agent
  once adoption begins.

Adoption (first-time attach to a pilot agent) is intentionally **not** part of
Lane 1. It requires the Notion UI today and should be scheduled as a separate,
deliberate step with explicit pilot selection.

## Worker Shape Guidance

A separate finding from the Lane 1 work: **Notion Workers are best for
Notion-native deterministic logic that uses `context.notion` as its primary
backend.** They are not a good home for tools that wrap external systems:

- External REST APIs (GitHub, Codeberg, etc.) belong in their own MCP servers.
- External datastores (Oracle, RAG corpora, vector indexes) should stay in
  purpose-built services and remain reachable via MCP. The Worker sandbox does
  not carry drivers like `oracledb`, and exposing credentials to a Worker is
  the wrong trust boundary.

When evaluating future `worker_candidate` tools, prefer those that read or
write Notion databases, enforce Notion-side invariants, or compose multiple
public-API reads into a single deterministic answer. Skip Worker
implementations for tools that are mostly thin wrappers over non-Notion
services.

## `check_gates` Parity Contract

The first Worker lane targets `check_gates`. Both implementations MUST return
exactly one of the following JSON shapes, with no additional keys:

```json
{"proceed": true, "cascade_depth": 1}
```

```json
{"halt": true, "reason": "pre_flight_active", "detail": "Pre-Flight Mode is active. All dispatch suspended."}
```

```json
{"halt": true, "reason": "cascade_depth_exceeded", "detail": "Cascade depth 5 >= limit 5."}
```

Contract requirements:

- Field set: `proceed`/`cascade_depth` OR `halt`/`reason`/`detail` — never mixed.
- `reason` is one of: `pre_flight_active`, `cascade_depth_exceeded`.
- `cascade_depth` is an integer ≥ 1. Default 1 when `work_item_id` is omitted
  or has no Cascade Depth property.
- Gate precedence: Pre-Flight check runs first. Cascade Depth runs only when
  `work_item_id` is provided.
- Max Cascade Depth default is 5 when Lab Control row is absent or null.
- Auth: Worker uses an official Notion integration token bound to the Lab
  databases; local path uses `NOTION_TOKEN` from `cli/config.py`. Both must
  read the same Lab Control DB and Work Items DB.

Golden fixtures live in `cli/test_dispatch.py` and `cli/check_gates_parity.py`
(see below). Worker implementation MUST pass the same fixture set before any
agent is reconfigured to call it.

## Rollback Procedure

Each Worker lane MUST have a documented rollback before any agent module is
pointed at it.

For `check_gates`:

1. Stop dispatch by enabling Pre-Flight Mode in Lab Control (halts all writes
   independent of which `check_gates` implementation runs).
2. For each agent currently configured to call the Worker `check_gates`:
   - `dump_agent <name>` to capture current instructions.
   - Edit instructions to reference the local MCP `check_gates` tool name.
   - `update_agent <name>` to republish.
3. Disable the Worker tool in the Notion Worker dashboard (or `ntn workers
   undeploy`) so no agent can resolve it.
4. Disable Pre-Flight Mode.
5. Verify with `chat_with_agent(lab_query, "How many Work Items are Dispatch
   Ready?", new_thread=True, wait=True)` and a manual `check_gates` call
   against the local MCP path.

Rollback MUST NOT touch Work Item state, audit log entries, or Lab Control
configuration beyond the Pre-Flight toggle.

## Backlog

1. ~~Add a `notion-platform-migration` tracking Work Item that links this
   audit.~~ Skipped by operator decision (2026-05-14): work that alters how
   Work Items are handled does not itself need a Work Item.
2. Add a Worker proof-of-concept branch for `check_gates` only.
3. Add a read-back smoke script that compares local `check_gates` and Worker
   `check_gates` output on a harmless Work Item
   (`cli/check_gates_parity.py`).
4. Add official Notion MCP as an optional read backend for `describe_database`,
   `query_database`, and `count_database`, but keep existing tools until exact
   count and aggregation contracts are validated.
5. Revisit private custom-agent APIs only when Notion exposes official support
   for workflow-parented instruction pages, custom-agent modules, resource
   grants, model selection, and publish/version operations.
6. Revisit agent chat/transcript capture only when External Agents API or Agent
   SDK access is available and can reproduce current thread handles, wait/poll
   semantics, and transcript fidelity.

## Acceptance Criteria

- ✅ Every `TOOL_CATALOG` entry has exactly one migration decision in the
  matrix (33/33 as of 2026-05-14).
- Lab return authority remains local for `handle_final_return` and
  `direct_closeout_return`.
- ✅ The first Worker lane is limited to read-only Lab tools unless a later
  plan explicitly authorizes write-path migration. Lane 1 satisfied by
  `check_gates` (deployed Worker `019e27e5-e70c-7762-bcf1-a43076d19525`,
  capability `checkGates`).
- Official MCP/API migration is limited to generic database reads until exact
  count, aggregation, auth, and headless-runtime behavior are verified.
- Private API usage is explicitly grouped under `internal_api_hold` rather than
  hidden behind generic migration language.

## Lane 1 Status (2026-05-14)

**Complete.**

| Item | State |
| --- | --- |
| Worker scaffold (`workers/check_gates/`) | created via `ntn workers new` |
| `checkGates` capability implementation | `workers/check_gates/src/index.ts` |
| TypeScript build | passes (`npm run check`) |
| Deployment | Worker `019e27e5-e70c-7762-bcf1-a43076d19525` live in Sam Scarrow's Notion |
| Runtime auth | `NOTION_API_TOKEN` pushed via `ntn workers env push` |
| Parity script | `cli/check_gates_parity.py` (supports `--worker --remote`) |
| Local vs Worker (local exec) | identical output, 2 fixtures |
| Local vs Worker (remote exec) | identical output, 2 fixtures |
| Catalog drift | 0 (33/33 entries match the matrix) |

Adoption (first-time attach to a pilot agent) is **not** part of Lane 1 and
is deferred to a separate planned step.
