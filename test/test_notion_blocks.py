import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli"))

import notion_blocks  # noqa: E402
import block_builder  # noqa: E402


class NotionBlocksTests(unittest.TestCase):
    def test_resolve_render_root_id_prefers_copied_source_root(self) -> None:
        blocks = {
            "wrapper": {
                "value": {
                    "id": "wrapper",
                    "type": "page",
                    "alive": True,
                    "content": ["copied-child"],
                    "format": {
                        "copied_from_pointer": {
                            "id": "source-root",
                            "table": "block",
                            "spaceId": "space-1",
                        }
                    },
                }
            },
        }

        self.assertEqual(
            notion_blocks.resolve_render_root_id("wrapper", blocks),
            "source-root",
        )

    def test_get_block_tree_dereferences_copied_shell_page(self) -> None:
        shell_response = {
            "recordMap": {
                "block": {
                    "wrapper": {
                        "value": {
                            "id": "wrapper",
                            "type": "page",
                            "alive": True,
                            "content": ["placeholder"],
                            "format": {
                                "copied_from_pointer": {
                                    "id": "source-root",
                                    "table": "block",
                                    "spaceId": "space-1",
                                }
                            },
                        }
                    },
                    "placeholder": {
                        "value": {
                            "id": "placeholder",
                            "type": "text",
                            "alive": True,
                            "format": {
                                "copied_from_pointer": {
                                    "id": "source-child",
                                    "table": "block",
                                    "spaceId": "space-1",
                                }
                            },
                        }
                    },
                }
            }
        }
        source_response = {
            "recordMap": {
                "block": {
                    "source-root": {
                        "value": {
                            "id": "source-root",
                            "type": "page",
                            "alive": True,
                            "content": ["real-child"],
                            "properties": {"title": [["Instructions"]]},
                        }
                    },
                    "real-child": {
                        "value": {
                            "id": "real-child",
                            "type": "text",
                            "alive": True,
                            "properties": {"title": [["Real content"]]},
                        }
                    },
                }
            }
        }
        with mock.patch.object(
            notion_blocks,
            "_post",
            side_effect=[shell_response, source_response],
        ) as post_mock:
            data = notion_blocks.get_block_tree("wrapper", "space-1", "token", "user-1")

        blocks = data.get("recordMap", {}).get("block", {})
        self.assertIn("source-root", blocks)
        self.assertIn("real-child", blocks)
        self.assertIn("wrapper", blocks)
        self.assertEqual(post_mock.call_count, 2)
        self.assertEqual(
            block_builder.blocks_to_markdown(blocks, "wrapper"),
            "Real content",
        )


if __name__ == "__main__":
    unittest.main()
