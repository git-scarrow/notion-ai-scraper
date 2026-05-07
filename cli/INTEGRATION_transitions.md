# Transition Log Integration

The transition log (cli/transitions.py) is a self-contained event-sourced sqlite
mirror of Lab dispatch/return events. Each existing call site needs one
`record_event(...)` call; failures must never block the Notion write path.

Add to imports in each file:

```python
from transitions import record_event
```

## Call sites

### 1. `cli/dispatch.py:807` — dispatch.accepted

After the `client.update_page(work_item_id, properties)` on line 801 and the
audit log block (lines 803-817), before `return { ... }` on line 819:

```python
try:
    record_event("dispatch.accepted", work_item_id, run_id=run_id,
                 actor="lab_dispatcher", payload={"prior_status": prior_status})
except Exception:
    pass
```

### 2. `cli/dispatch.py:1072` — return.received

After `client.update_page(work_item_id, update_props)` on line 1072:

```python
try:
    record_event("return.received", work_item_id, run_id=run_id,
                 actor=lane or "execution_plane",
                 payload={"status": status, "verdict": verdict, "model": model})
except Exception:
    pass
```

### 3. `cli/dispatch.py:1210` — return.direct_closeout

Inside `direct_closeout_return`, immediately before the `return handle_final_return(...)`
on line 1193 (so the event records even if the inner call later short-circuits
on idempotency):

```python
try:
    record_event("return.direct_closeout", work_item_id, run_id=generated_run_id,
                 actor="direct_closeout",
                 payload={"status": status, "verdict": verdict, "lane": lane})
except Exception:
    pass
```

### 4. `cli/github_return.py:140` — github.closeout

After the `client.append_block_children(page_id, blocks)` on line 144 (or after
the `client.update_page` on line 115/121 if blocks are empty), before
`perform_return` returns the evidence tag:

```python
try:
    record_event("github.closeout", page_id, run_id=None,
                 actor="github_webhook",
                 payload={"evidence": evidence_tag, "status": target_status})
except Exception:
    pass
```

### 5. intake.triggered — TBD

Intake Clerk fires inside Notion as an automation triggered by
`Return Received At`. There is no Python write site in this repo today.
**TBD: identify intake clerk write site.** Candidates to audit:
- `cli/webhook_receiver.py` (if it ever observes intake completion)
- A future intake-side return handshake

When found, add:

```python
record_event("intake.triggered", work_item_id, run_id=run_id, actor="intake_clerk")
```

## MCP registration

In `cli/mcp_server.py`, after the `mcp = FastMCP(...)` construction and the
existing `register_*` calls:

```python
from transitions import register_transition_tools
register_transition_tools(mcp)
```

This exposes `transition_events(work_item_id)` and
`transition_replay_check(work_item_id)`.
