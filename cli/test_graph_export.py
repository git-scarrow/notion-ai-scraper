from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import graph_export
from graph_export import (
    GraphEdge,
    GraphNode,
    LabGraph,
    diff_graphs,
    from_snapshot,
    to_dot,
    to_json,
    to_mermaid,
)


@pytest.fixture
def synthetic_snapshot() -> dict:
    return {
        "databases": [
            {
                "key": "work_items",
                "label": "Work Items",
                "notion_public_id": "pub-wi",
                "notion_internal_id": "int-wi",
            },
            {
                "key": "audit_log",
                "label": "Audit Log",
                "notion_public_id": "pub-al",
                "notion_internal_id": "int-al",
            },
        ],
        "agents": [
            {
                "key": "lab_query",
                "label": "Lab Query",
                "model": "fireworks-minimax-m2.5",
                "live_present": True,
                "registry_present": True,
                "triggers": [
                    {
                        "id": "trig-1",
                        "type": "notion.page.updated",
                        "enabled": True,
                        "database_key": "work_items",
                        "database_label": "Work Items",
                        "properties": [{"name": "Status", "type": "status"}],
                    }
                ],
                "permissions": [
                    {
                        "resource_type": "database",
                        "resource_key": "work_items",
                        "resource_label": "Work Items",
                        "access": "read_and_write",
                    },
                    {
                        "resource_type": "database",
                        "resource_key": "audit_log",
                        "resource_label": "Audit Log",
                        "access": "reader",
                    },
                ],
                "published_runtime_config": {
                    "mcp_servers": [
                        {
                            "name": "notion",
                            "serverUrl": "https://example/mcp",
                            "enabledToolNames": ["query_database", "describe_database"],
                        }
                    ]
                },
            },
            {
                "key": "intake_clerk",
                "label": "Intake Clerk",
                "model": "apricot-sorbet-high",
                "live_present": True,
                "registry_present": True,
                "triggers": [],
                "permissions": [
                    {
                        "resource_type": "database",
                        "resource_key": "audit_log",
                        "resource_label": "Audit Log",
                        "access": "read_and_write",
                    }
                ],
                "published_runtime_config": {"mcp_servers": []},
            },
        ],
        "automations": [],
        "status_transitions": [
            {"from": "Not Started", "to": "In Progress", "count": 5},
            {"from": "In Progress", "to": "Returned", "count": 4},
        ],
    }


def test_from_snapshot_node_and_edge_counts(synthetic_snapshot):
    graph = from_snapshot(synthetic_snapshot)

    kinds = {n.kind for n in graph.nodes}
    assert {"agent", "database", "trigger", "tool", "status"} <= kinds

    nodes_by_kind = {}
    for node in graph.nodes:
        nodes_by_kind.setdefault(node.kind, []).append(node)
    assert len(nodes_by_kind["agent"]) == 2
    assert len(nodes_by_kind["database"]) == 2
    assert len(nodes_by_kind["trigger"]) == 1
    assert len(nodes_by_kind["tool"]) == 2
    assert len(nodes_by_kind["status"]) == 3

    fires_edges = [e for e in graph.edges if e.kind == "fires"]
    uses_tool_edges = [e for e in graph.edges if e.kind == "uses_tool"]
    write_edges = [e for e in graph.edges if e.kind == "writes"]
    read_edges = [e for e in graph.edges if e.kind == "reads"]
    transition_edges = [e for e in graph.edges if e.kind == "transitions_to"]

    assert len(fires_edges) == 1
    assert len(uses_tool_edges) == 2
    assert len(write_edges) == 2
    assert len(read_edges) == 1
    assert len(transition_edges) == 2


def test_node_id_conventions(synthetic_snapshot):
    graph = from_snapshot(synthetic_snapshot)
    ids = {n.id for n in graph.nodes}
    assert "agent:lab_query" in ids
    assert "agent:intake_clerk" in ids
    assert "db:work_items" in ids
    assert "db:audit_log" in ids
    assert "trigger:lab_query:notion.page.updated:trig-1" in ids
    assert "tool:notion.query_database" in ids
    assert "status:Not Started" in ids


def test_to_json_is_deterministic(synthetic_snapshot):
    g1 = from_snapshot(synthetic_snapshot)
    g2 = from_snapshot(synthetic_snapshot)
    a = to_json(g1)
    b = to_json(g2)
    assert a == b
    parsed = json.loads(a)
    assert parsed["nodes"] == sorted(parsed["nodes"], key=lambda n: n["id"])


def test_to_dot_starts_with_digraph(synthetic_snapshot):
    dot = to_dot(from_snapshot(synthetic_snapshot))
    assert dot.startswith("digraph")
    assert "cluster_agent" in dot
    assert "cluster_database" in dot


def test_to_mermaid_starts_with_graph(synthetic_snapshot):
    mermaid = to_mermaid(from_snapshot(synthetic_snapshot))
    assert mermaid.startswith("graph LR") or mermaid.startswith("graph TD")
    assert "fires" in mermaid
    assert "uses_tool" in mermaid


def test_diff_graphs_detects_changes(synthetic_snapshot):
    base = from_snapshot(synthetic_snapshot)

    modified = json.loads(json.dumps(synthetic_snapshot))
    modified["agents"].append(
        {
            "key": "new_agent",
            "label": "New Agent",
            "triggers": [],
            "permissions": [
                {
                    "resource_type": "database",
                    "resource_key": "work_items",
                    "resource_label": "Work Items",
                    "access": "reader",
                }
            ],
            "published_runtime_config": {"mcp_servers": []},
        }
    )
    modified["agents"][0]["permissions"] = [
        p for p in modified["agents"][0]["permissions"] if p["resource_key"] != "audit_log"
    ]
    new_graph = from_snapshot(modified)

    diff = diff_graphs(base, new_graph)
    added_node_ids = {n["id"] for n in diff["added_nodes"]}
    assert "agent:new_agent" in added_node_ids

    added_edge_pairs = {(e["source"], e["target"], e["kind"]) for e in diff["added_edges"]}
    assert ("agent:new_agent", "db:work_items", "reads") in added_edge_pairs

    removed_edge_pairs = {(e["source"], e["target"], e["kind"]) for e in diff["removed_edges"]}
    assert ("agent:lab_query", "db:audit_log", "reads") in removed_edge_pairs


def test_source_snapshot_keys_recorded(synthetic_snapshot):
    graph = from_snapshot(synthetic_snapshot)
    assert "agents" in graph.source_snapshot_keys
    assert "databases" in graph.source_snapshot_keys
    assert "status_transitions" in graph.source_snapshot_keys
