import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli"))

mcp_module = types.ModuleType("mcp")
server_module = types.ModuleType("mcp.server")
fastmcp_module = types.ModuleType("mcp.server.fastmcp")


class _FakeFastMCP:
    def __init__(self, *_args, **_kwargs):
        pass

    def tool(self):
        def decorator(func):
            return func

        return decorator

    def run(self):
        return None


fastmcp_module.FastMCP = _FakeFastMCP
sys.modules.setdefault("mcp", mcp_module)
sys.modules.setdefault("mcp.server", server_module)
sys.modules.setdefault("mcp.server.fastmcp", fastmcp_module)

import claude_mcp_server  # noqa: E402


class ClaudeMCPServerTests(unittest.TestCase):
    def test_resolve_chat_targets_rejects_ambiguous_match(self) -> None:
        convs = [
            {"uuid": "conv-1", "name": "Daily Sync"},
            {"uuid": "conv-2", "name": "Daily Sync Follow-up"},
        ]

        resolved, errors = claude_mcp_server._resolve_chat_targets(convs, "Daily Sync")

        self.assertEqual(resolved, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("Multiple matches for 'Daily Sync'", errors[0])
        self.assertIn("conv-1", errors[0])
        self.assertIn("conv-2", errors[0])

    def test_extract_chats_writes_selected_transcripts(self) -> None:
        convs = [
            {"uuid": "conv-1", "name": "Alpha Chat", "created_at": "2026-04-07T12:00:00Z"},
            {"uuid": "conv-2", "name": "Beta Chat", "created_at": "2026-04-06T12:00:00Z"},
        ]
        messages_by_uuid = {
            "conv-1": [{"role": "human", "text": "Hello"}],
            "conv-2": [{"role": "assistant", "text": "World"}],
        }
        client = mock.Mock()
        client.list_conversations.return_value = convs

        def get_messages_side_effect(_, conv_uuid: str):
            return messages_by_uuid[conv_uuid]

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            claude_mcp_server,
            "_get_client",
            return_value=client,
        ), mock.patch.object(
            claude_mcp_server,
            "_get_messages",
            side_effect=get_messages_side_effect,
        ):
            result = claude_mcp_server.claude_extract_chats(
                "project-1",
                "Alpha Chat, conv-2",
                tmpdir,
            )

            alpha_path = Path(tmpdir) / "Alpha_Chat.md"
            beta_path = Path(tmpdir) / "Beta_Chat.md"
            self.assertTrue(alpha_path.exists())
            self.assertTrue(beta_path.exists())
            self.assertIn("# Alpha Chat", alpha_path.read_text())
            self.assertIn("[HUMAN]", alpha_path.read_text())
            self.assertIn("# Beta Chat", beta_path.read_text())
            self.assertIn("[ASSISTANT]", beta_path.read_text())
            self.assertIn("Extracted 2 chat(s)", result)

    def test_extract_chats_disambiguates_duplicate_safe_names(self) -> None:
        convs = [
            {"uuid": "abc12345-0000", "name": "Roadmap/Q2", "created_at": "2026-04-07T12:00:00Z"},
            {"uuid": "def67890-0000", "name": "Roadmap:Q2", "created_at": "2026-04-07T13:00:00Z"},
        ]
        client = mock.Mock()
        client.list_conversations.return_value = convs

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            claude_mcp_server,
            "_get_client",
            return_value=client,
        ), mock.patch.object(
            claude_mcp_server,
            "_get_messages",
            return_value=[{"role": "human", "text": "Hi"}],
        ):
            claude_mcp_server.claude_extract_chats("project-1", "abc12345-0000,def67890-0000", tmpdir)

            self.assertTrue((Path(tmpdir) / "RoadmapQ2.md").exists())
            self.assertTrue((Path(tmpdir) / "RoadmapQ2_def67890.md").exists())


if __name__ == "__main__":
    unittest.main()
