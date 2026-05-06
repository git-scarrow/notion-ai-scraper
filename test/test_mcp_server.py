import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli"))

import mcp_server  # noqa: E402


class MCPServerTests(unittest.TestCase):
    def test_start_agent_run_returns_non_blocking_payload(self) -> None:
        with mock.patch.object(mcp_server, "chat_with_agent", return_value='{"status":"queued"}') as chat_mock:
            result = mcp_server.start_agent_run("librarian", "Hello", new_thread=True)

        self.assertEqual(json.loads(result)["status"], "queued")
        chat_mock.assert_called_once_with(
            agent_name="librarian",
            message="Hello",
            thread_id=None,
            new_thread=True,
            wait=False,
        )

    def test_chat_with_agent_wait_timeout_returns_tracking_payload(self) -> None:
        with mock.patch.object(mcp_server, "_load_registry", return_value={
            "librarian": {
                "notion_internal_id": "wf-1",
                "space_id": "space-1",
            }
        }), mock.patch.object(mcp_server, "_get_auth", return_value=("token", "user-1")), mock.patch.object(
            mcp_server.notion_client,
            "list_workflow_threads",
            return_value=[],
        ), mock.patch.object(
            mcp_server.notion_client,
            "create_workflow_thread",
            return_value="thread-1",
        ), mock.patch.object(
            mcp_server.notion_client,
            "get_workflow_record",
            return_value={"data": {"model": {"type": "auto"}}},
        ) as workflow_mock, mock.patch.object(
            mcp_server.notion_client,
            "send_agent_message",
            return_value="msg-1",
        ), mock.patch.object(
            mcp_server.notion_client,
            "wait_for_agent_response_state",
            return_value={"status": "pending", "content": "Still working", "turns": []},
        ):
            result = json.loads(
                mcp_server.chat_with_agent("librarian", "Hello", wait=True, timeout=30)
            )

        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["thread_id"], "thread-1")
        self.assertEqual(result["message_id"], "msg-1")
        self.assertEqual(result["content"], "Still working")
        self.assertEqual(result["requested_timeout_seconds"], 30)
        self.assertEqual(result["effective_timeout_seconds"], 30)
        self.assertEqual(
            result["tracking"]["check_agent_response"],
            {"thread_id": "thread-1", "after_msg_id": "msg-1", "space_id": mcp_server.CFG.space_id},
        )
        workflow_mock.assert_called_once_with(
            "wf-1", "token", "user-1", space_id="space-1"
        )

    def test_chat_with_agent_caps_wait_to_transport_safe_budget(self) -> None:
        with mock.patch.object(mcp_server, "_load_registry", return_value={
            "librarian": {
                "notion_internal_id": "wf-1",
                "space_id": "space-1",
            }
        }), mock.patch.object(mcp_server, "_get_auth", return_value=("token", "user-1")), mock.patch.object(
            mcp_server.notion_client,
            "list_workflow_threads",
            return_value=[{"id": "thread-1"}],
        ), mock.patch.object(
            mcp_server.notion_client,
            "get_workflow_record",
            return_value={"data": {"model": {"type": "auto"}}},
        ), mock.patch.object(
            mcp_server.notion_client,
            "send_agent_message",
            return_value="msg-1",
        ), mock.patch.object(
            mcp_server.notion_client,
            "wait_for_agent_response_state",
            return_value={"status": "pending", "content": None, "turns": []},
        ) as wait_mock:
            result = json.loads(
                mcp_server.chat_with_agent("librarian", "Hello", wait=True, timeout=180)
            )

        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["requested_timeout_seconds"], 180)
        self.assertEqual(
            result["effective_timeout_seconds"],
            mcp_server._SAFE_TOOL_WAIT_SECONDS,
        )
        self.assertIn("transport-safe wait budget", result["note"])
        self.assertEqual(wait_mock.call_args.kwargs["timeout"], mcp_server._SAFE_TOOL_WAIT_SECONDS)

    def test_chat_with_agent_wait_complete_returns_content_payload(self) -> None:
        with mock.patch.object(mcp_server, "_load_registry", return_value={
            "librarian": {
                "notion_internal_id": "wf-1",
                "space_id": "space-1",
            }
        }), mock.patch.object(mcp_server, "_get_auth", return_value=("token", "user-1")), mock.patch.object(
            mcp_server.notion_client,
            "list_workflow_threads",
            return_value=[{"id": "thread-1"}],
        ), mock.patch.object(
            mcp_server.notion_client,
            "get_workflow_record",
            return_value={"data": {"model": {"type": "auto"}}},
        ), mock.patch.object(
            mcp_server.notion_client,
            "send_agent_message",
            return_value="msg-1",
        ), mock.patch.object(
            mcp_server.notion_client,
            "wait_for_agent_response_state",
            return_value={"status": "complete", "content": "Done", "turns": []},
        ):
            result = json.loads(
                mcp_server.chat_with_agent("librarian", "Hello", wait=True, timeout=30)
            )

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["content"], "Done")

    def test_check_agent_response_surfaces_pending_partial_content(self) -> None:
        with mock.patch.object(mcp_server, "_get_auth", return_value=("token", "user-1")), mock.patch.object(
            mcp_server.notion_client,
            "get_agent_response_state",
            return_value={"status": "pending", "content": "Thinking", "turns": []},
        ):
            result = json.loads(mcp_server.check_agent_response("thread-1", "msg-1"))

        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["content"], "Thinking")

    def test_check_agent_response_passes_space_id(self) -> None:
        with mock.patch.object(mcp_server, "_get_auth", return_value=("token", "user-1")), mock.patch.object(
            mcp_server.notion_client,
            "get_agent_response_state",
            return_value={"status": "pending", "content": None, "turns": []},
        ) as state_mock:
            json.loads(mcp_server.check_agent_response("thread-1", "msg-1"))

        self.assertEqual(state_mock.call_args.kwargs["space_id"], mcp_server.CFG.space_id)

    def test_update_agent_uses_shared_impl(self) -> None:
        with mock.patch.object(mcp_server, "_update_agent_impl", return_value="ok") as impl:
            result = mcp_server.update_agent("librarian", "# Hello", publish=False)

        self.assertEqual(result, "ok")
        impl.assert_called_once_with("librarian", "# Hello", False)

    def test_update_agent_from_file_reads_markdown_and_uses_shared_impl(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write("# Title\n\nBody")
            path = f.name

        try:
            with mock.patch.object(mcp_server, "_update_agent_impl", return_value="ok") as impl:
                result = mcp_server.update_agent_from_file("librarian", path, publish=True)
        finally:
            Path(path).unlink(missing_ok=True)

        self.assertEqual(result, "ok")
        impl.assert_called_once_with("librarian", "# Title\n\nBody", True)

    def test_get_agent_config_raw_tools_reads_nested_mcp_state(self) -> None:
        registry = {
            "lab_query": {
                "label": "Lab Query",
                "notion_internal_id": "wf-1",
                "notion_public_id": "public-1",
                "space_id": "space-1",
            }
        }
        modules = [
            {
                "name": "Notion",
                "type": "notion",
                "permissions": [
                    {
                        "actions": ["reader"],
                        "identifier": {"type": "workspacePublic"},
                    },
                    {
                        "actions": ["reader"],
                        "identifier": {
                            "type": "pageOrCollectionViewBlock",
                            "blockId": "page-1",
                        },
                    },
                ],
            },
            {
                "name": "Lab Control Plane",
                "type": "mcpServer",
                "state": {
                    "serverUrl": "https://mcp.example.test/mcp/notion",
                    "officialName": "Notion API",
                    "preferredTransport": "streamableHttp",
                    "connectionPointer": {"id": "conn-1"},
                    "enabledToolNames": [
                        "API-query-data-source",
                        "API-retrieve-a-data-source",
                    ],
                    "tools": [
                        {
                            "name": "API-query-data-source",
                            "title": "Query Data Source",
                        },
                        {
                            "name": "API-retrieve-a-data-source",
                            "title": "Retrieve A Data Source",
                        },
                        {
                            "name": "API-retrieve-a-database",
                            "title": "Retrieve A Database",
                        },
                    ],
                },
            },
        ]

        with mock.patch.object(mcp_server, "_load_registry", return_value=registry), mock.patch.object(
            mcp_server,
            "_get_auth",
            return_value=("token", "user-1"),
        ), mock.patch.object(
            mcp_server.notion_client,
            "get_workflow_record",
            return_value={"data": {"model": {"type": "fireworks-minimax-m2.5"}}},
        ), mock.patch.object(
            mcp_server.notion_client,
            "get_agent_modules",
            return_value={
                "model": "fireworks-minimax-m2.5",
                "model_name": "MiniMax M2.5",
                "modules": modules,
            },
        ):
            result = mcp_server.get_agent_config_raw("lab_query", section="tools")

        self.assertIn("Model: MiniMax M2.5 (fireworks-minimax-m2.5)", result)
        self.assertIn("[MCP] Lab Control Plane (Notion API)", result)
        self.assertIn("URL: https://mcp.example.test/mcp/notion", result)
        self.assertIn("Connection ID: conn-1", result)
        self.assertIn("Enabled: 2/3 tools", result)
        self.assertIn("[ON] API-query-data-source: Query Data Source", result)
        self.assertIn("[off] API-retrieve-a-database: Retrieve A Database", result)
        self.assertIn("Workspace public pages — reader", result)
        self.assertIn("page-1 — reader", result)

    def test_build_update_message_formats_counts(self) -> None:
        msg = mcp_server._build_update_message(
            "librarian",
            {
                "unchanged": 10,
                "updated": 2,
                "inserted": 1,
                "deleted": 3,
                "ops": 17,
            },
        )

        self.assertEqual(
            msg,
            "Updated librarian (10 unchanged, 2 updated, 1 inserted, 3 deleted, 17 ops in 1 tx).",
        )


if __name__ == "__main__":
    unittest.main()
