# Graph Export Integration

`cli/graph_export.py` consumes the dict returned by `lab_topology.compile_snapshot()` and emits a deterministic node/edge graph. It does not call Notion itself.

## Plug-in to `cli/mcp_server.py`

Add near the existing `database_tools` import block (after the `get_lab_topology` definition is fine):

```python
import graph_export
graph_export.register_graph_tools(mcp)
```

This adds two MCP tools alongside `get_lab_topology`:

- `lab_graph(format="json"|"dot"|"mermaid")` — compiles the live snapshot and renders.
- `lab_graph_drift(prev_path)` — diffs the current graph against a previously saved JSON file.

## Persisting baselines

Save a baseline next to the other lab artifacts so drift checks have something to diff against:

```bash
cli/.venv/bin/python -c "import sys; sys.path.insert(0,'cli'); \
  import lab_topology, graph_export; \
  s = lab_topology.compile_snapshot(); \
  open('cli/lab_graph_baseline.json','w').write(graph_export.to_json(graph_export.from_snapshot(s)))"
```

Then later:

```python
graph_export.diff_graphs(
    graph_export.graph_from_json(open("cli/lab_graph_baseline.json").read()),
    graph_export.from_snapshot(lab_topology.compile_snapshot()),
)
```

## Sample DOT (truncated)

```
digraph LabGraph {
  rankdir=LR;
  node [shape=box, style=rounded];
  subgraph cluster_agent {
    label="agent";
    "agent:lab_query" [label="Lab Query"];
  }
  "trigger:lab_query:notion.page.updated:trig-1" -> "agent:lab_query" [label="fires", color="#d62728", style=bold];
  "agent:lab_query" -> "db:work_items" [label="writes", color="#9467bd", style=bold];
}
```

## Sample Mermaid (truncated)

```
graph LR
  n_agent_lab_query["agent: Lab Query"]
  n_db_work_items["database: Work Items"]
  n_trigger_lab_query_notion_page_updated_trig_1["trigger: notion.page.updated"]
  n_trigger_lab_query_notion_page_updated_trig_1 -->|fires| n_agent_lab_query
  n_agent_lab_query -->|writes| n_db_work_items
```

## Notes

- Snapshot keys consumed are recorded on `LabGraph.source_snapshot_keys` for provenance.
- `to_json` sorts nodes/edges so `git diff` of `lab_graph_baseline.json` is meaningful.
- Status-transition edges are populated only if a future `compile_snapshot()` revision adds a `status_transitions` key (`[{"from": "...", "to": "...", "count": N}]`); the export tolerates its absence.
