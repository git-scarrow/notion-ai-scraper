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
        ), mock.patch.object(
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
