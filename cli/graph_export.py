from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Any, Literal

NodeKind = Literal["agent", "trigger", "tool", "status", "database", "automation"]
EdgeKind = Literal["fires", "uses_tool", "reads", "writes", "transitions_to", "permits"]

_GRAPH_VERSION = date.today().isoformat()


@dataclass(frozen=True)
class GraphNode:
    id: str
    kind: NodeKind
    label: str
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    kind: EdgeKind
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class LabGraph:
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    version: str = _GRAPH_VERSION
    source_snapshot_keys: list[str] = field(default_factory=list)


def _agent_node_id(agent_key: str) -> str:
    return f"agent:{agent_key}"


def _trigger_node_id(agent_key: str, trigger_kind: str, trigger_id_or_index: str | int) -> str:
    return f"trigger:{agent_key}:{trigger_kind}:{trigger_id_or_index}"


def _tool_node_id(tool_name: str) -> str:
    return f"tool:{tool_name}"


def _status_node_id(status_name: str) -> str:
    return f"status:{status_name}"


def _db_node_id(db_key: str) -> str:
    return f"db:{db_key}"


def _automation_node_id(db_key: str, automation_id: str) -> str:
    return f"automation:{db_key}:{automation_id}"


def _access_to_edge_kind(access: str) -> EdgeKind:
    if access == "read_and_write":
        return "writes"
    if access == "reader":
        return "reads"
    return "permits"


def from_snapshot(snapshot: dict) -> LabGraph:
    consumed: list[str] = []
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []

    def add_node(node: GraphNode) -> None:
        existing = nodes.get(node.id)
        if existing is None:
            nodes[node.id] = node
            return
        merged_attrs = {**existing.attrs, **node.attrs}
        nodes[node.id] = GraphNode(id=node.id, kind=node.kind, label=existing.label or node.label, attrs=merged_attrs)

    databases = snapshot.get("databases") or []
    if databases:
        consumed.append("databases")
    for database in databases:
        db_key = database.get("key") or database.get("notion_internal_id") or "unknown"
        add_node(
            GraphNode(
                id=_db_node_id(db_key),
                kind="database",
                label=database.get("label") or db_key,
                attrs={
                    "notion_public_id": database.get("notion_public_id"),
                    "notion_internal_id": database.get("notion_internal_id"),
                },
            )
        )

    agents = snapshot.get("agents") or []
    if agents:
        consumed.append("agents")
    for agent in agents:
        agent_key = agent["key"]
        agent_id = _agent_node_id(agent_key)
        add_node(
            GraphNode(
                id=agent_id,
                kind="agent",
                label=agent.get("label") or agent_key,
                attrs={
                    "model": agent.get("model"),
                    "live_present": agent.get("live_present"),
                    "registry_present": agent.get("registry_present"),
                },
            )
        )

        for index, trigger in enumerate(agent.get("triggers") or []):
            trigger_kind = trigger.get("type") or "unknown"
            trigger_raw_id = trigger.get("id") or index
            trigger_id = _trigger_node_id(agent_key, trigger_kind, trigger_raw_id)
            add_node(
                GraphNode(
                    id=trigger_id,
                    kind="trigger",
                    label=f"{trigger_kind}",
                    attrs={
                        "enabled": trigger.get("enabled", True),
                        "database_key": trigger.get("database_key"),
                        "properties": [p.get("name") for p in trigger.get("properties") or []],
                    },
                )
            )
            edges.append(
                GraphEdge(
                    source=trigger_id,
                    target=agent_id,
                    kind="fires",
                    attrs={"enabled": trigger.get("enabled", True)},
                )
            )
            db_key = trigger.get("database_key")
            if db_key:
                add_node(
                    GraphNode(
                        id=_db_node_id(db_key),
                        kind="database",
                        label=trigger.get("database_label") or db_key,
                        attrs={},
                    )
                )

        for permission in agent.get("permissions") or []:
            if permission.get("resource_type") != "database":
                continue
            db_key = permission.get("resource_key")
            if not db_key:
                continue
            add_node(
                GraphNode(
                    id=_db_node_id(db_key),
                    kind="database",
                    label=permission.get("resource_label") or db_key,
                    attrs={},
                )
            )
            edges.append(
                GraphEdge(
                    source=agent_id,
                    target=_db_node_id(db_key),
                    kind=_access_to_edge_kind(permission.get("access", "")),
                    attrs={"access": permission.get("access")},
                )
            )

        runtime_config = agent.get("published_runtime_config") or agent.get("draft_runtime_config") or {}
        for server in runtime_config.get("mcp_servers") or []:
            server_name = server.get("name") or server.get("serverUrl") or "mcp"
            for tool_name in server.get("enabledToolNames") or []:
                qualified = f"{server_name}.{tool_name}"
                add_node(
                    GraphNode(
                        id=_tool_node_id(qualified),
                        kind="tool",
                        label=tool_name,
                        attrs={"server": server_name, "server_url": server.get("serverUrl")},
                    )
                )
                edges.append(
                    GraphEdge(
                        source=agent_id,
                        target=_tool_node_id(qualified),
                        kind="uses_tool",
                        attrs={"server": server_name},
                    )
                )

    automations = snapshot.get("automations") or []
    if automations:
        consumed.append("automations")
    for automation in automations:
        db_key = automation.get("database_key") or "unknown"
        automation_id = automation.get("id") or "unknown"
        node_id = _automation_node_id(db_key, automation_id)
        add_node(
            GraphNode(
                id=node_id,
                kind="automation",
                label=automation.get("event_type") or "automation",
                attrs={
                    "enabled": automation.get("enabled", True),
                    "database_key": db_key,
                },
            )
        )
        edges.append(
            GraphEdge(
                source=_db_node_id(db_key),
                target=node_id,
                kind="fires",
                attrs={},
            )
        )

    transitions = snapshot.get("status_transitions") or []
    if transitions:
        consumed.append("status_transitions")
    for transition in transitions:
        source_status = transition.get("from") or transition.get("source")
        target_status = transition.get("to") or transition.get("target")
        if not source_status or not target_status:
            continue
        add_node(GraphNode(id=_status_node_id(source_status), kind="status", label=source_status, attrs={}))
        add_node(GraphNode(id=_status_node_id(target_status), kind="status", label=target_status, attrs={}))
        edges.append(
            GraphEdge(
                source=_status_node_id(source_status),
                target=_status_node_id(target_status),
                kind="transitions_to",
                attrs={"count": transition.get("count", 0)},
            )
        )

    sorted_nodes = sorted(nodes.values(), key=lambda n: n.id)
    sorted_edges = sorted(
        edges,
        key=lambda e: (e.source, e.target, e.kind, json.dumps(e.attrs, sort_keys=True, default=str)),
    )
    return LabGraph(
        nodes=sorted_nodes,
        edges=sorted_edges,
        version=_GRAPH_VERSION,
        source_snapshot_keys=sorted(set(consumed)),
    )


_DOT_EDGE_STYLES: dict[str, str] = {
    "fires": "color=\"#d62728\", style=bold",
    "uses_tool": "color=\"#1f77b4\", style=dashed",
    "reads": "color=\"#2ca02c\"",
    "writes": "color=\"#9467bd\", style=bold",
    "transitions_to": "color=\"#ff7f0e\"",
    "permits": "color=\"#7f7f7f\", style=dotted",
}


def _dot_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("\"", "\\\"")


def to_dot(graph: LabGraph) -> str:
    lines: list[str] = ["digraph LabGraph {", "  rankdir=LR;", "  node [shape=box, style=rounded];"]
    by_kind: dict[str, list[GraphNode]] = {}
    for node in graph.nodes:
        by_kind.setdefault(node.kind, []).append(node)
    for kind in sorted(by_kind):
        lines.append(f"  subgraph cluster_{kind} {{")
        lines.append(f"    label=\"{kind}\";")
        for node in by_kind[kind]:
            lines.append(f"    \"{_dot_escape(node.id)}\" [label=\"{_dot_escape(node.label)}\"];")
        lines.append("  }")
    for edge in graph.edges:
        style = _DOT_EDGE_STYLES.get(edge.kind, "")
        attrs = f"label=\"{edge.kind}\""
        if style:
            attrs = f"{attrs}, {style}"
        lines.append(f"  \"{_dot_escape(edge.source)}\" -> \"{_dot_escape(edge.target)}\" [{attrs}];")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _mermaid_id(raw: str) -> str:
    return "n_" + "".join(c if c.isalnum() else "_" for c in raw)


def to_mermaid(graph: LabGraph) -> str:
    lines: list[str] = ["graph LR"]
    for node in graph.nodes:
        label = node.label.replace("\"", "'")
        lines.append(f"  {_mermaid_id(node.id)}[\"{node.kind}: {label}\"]")
    for edge in graph.edges:
        lines.append(
            f"  {_mermaid_id(edge.source)} -->|{edge.kind}| {_mermaid_id(edge.target)}"
        )
    return "\n".join(lines) + "\n"


def _node_to_dict(node: GraphNode) -> dict[str, Any]:
    return {"id": node.id, "kind": node.kind, "label": node.label, "attrs": node.attrs}


def _edge_to_dict(edge: GraphEdge) -> dict[str, Any]:
    return {"source": edge.source, "target": edge.target, "kind": edge.kind, "attrs": edge.attrs}


def to_json(graph: LabGraph) -> str:
    payload = {
        "version": graph.version,
        "source_snapshot_keys": sorted(graph.source_snapshot_keys),
        "nodes": [_node_to_dict(n) for n in sorted(graph.nodes, key=lambda x: x.id)],
        "edges": [
            _edge_to_dict(e)
            for e in sorted(
                graph.edges,
                key=lambda x: (x.source, x.target, x.kind, json.dumps(x.attrs, sort_keys=True, default=str)),
            )
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True, default=str)


def _edge_key(edge: GraphEdge) -> tuple[str, str, str, str]:
    return (edge.source, edge.target, edge.kind, json.dumps(edge.attrs, sort_keys=True, default=str))


def diff_graphs(a: LabGraph, b: LabGraph) -> dict:
    a_node_ids = {n.id for n in a.nodes}
    b_node_ids = {n.id for n in b.nodes}
    a_nodes_by_id = {n.id: n for n in a.nodes}
    b_nodes_by_id = {n.id: n for n in b.nodes}
    a_edges = {_edge_key(e): e for e in a.edges}
    b_edges = {_edge_key(e): e for e in b.edges}
    added_node_ids = sorted(b_node_ids - a_node_ids)
    removed_node_ids = sorted(a_node_ids - b_node_ids)
    added_edge_keys = sorted(set(b_edges) - set(a_edges))
    removed_edge_keys = sorted(set(a_edges) - set(b_edges))
    return {
        "added_nodes": [_node_to_dict(b_nodes_by_id[i]) for i in added_node_ids],
        "removed_nodes": [_node_to_dict(a_nodes_by_id[i]) for i in removed_node_ids],
        "added_edges": [_edge_to_dict(b_edges[k]) for k in added_edge_keys],
        "removed_edges": [_edge_to_dict(a_edges[k]) for k in removed_edge_keys],
    }


def graph_from_json(payload: str | dict) -> LabGraph:
    data = json.loads(payload) if isinstance(payload, str) else payload
    nodes = [
        GraphNode(id=n["id"], kind=n["kind"], label=n.get("label", n["id"]), attrs=n.get("attrs", {}))
        for n in data.get("nodes", [])
    ]
    edges = [
        GraphEdge(source=e["source"], target=e["target"], kind=e["kind"], attrs=e.get("attrs", {}))
        for e in data.get("edges", [])
    ]
    return LabGraph(
        nodes=nodes,
        edges=edges,
        version=data.get("version", _GRAPH_VERSION),
        source_snapshot_keys=data.get("source_snapshot_keys", []),
    )


def register_graph_tools(mcp) -> None:
    import lab_topology

    @mcp.tool()
    def lab_graph(format: str = "json") -> str:
        """Render the live Lab topology as a deterministic graph.

        format: "json" (default), "dot", or "mermaid".
        """
        snapshot = lab_topology.compile_snapshot()
        graph = from_snapshot(snapshot)
        fmt = (format or "json").lower()
        if fmt == "dot":
            return to_dot(graph)
        if fmt == "mermaid":
            return to_mermaid(graph)
        return to_json(graph)

    @mcp.tool()
    def lab_graph_drift(prev_path: str) -> str:
        """Diff the current Lab graph against a previously persisted JSON graph.

        prev_path: filesystem path to a JSON file produced by lab_graph(format="json").
        """
        with open(prev_path, "r", encoding="utf-8") as handle:
            prev = graph_from_json(handle.read())
        snapshot = lab_topology.compile_snapshot()
        current = from_snapshot(snapshot)
        return json.dumps(diff_graphs(prev, current), indent=2, sort_keys=True, default=str)
