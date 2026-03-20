import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli"))

import notion_blocks  # noqa: E402
import block_builder  # noqa: E402


class NotionBlocksTests(unittest.TestCase):
    def test_extract_crdt_title_state_requires_matching_visible_title_node(self) -> None:
        block = {
            "properties": {"title": [["Hello world"]]},
            "crdt_data": {
                "title": {
                    "r": "root",
                    "n": {
                        "root": {
                            "s": {
                                "x": "text-instance-1",
                                "i": [
                                    {
                                        "t": "t",
                                        "i": ["item-seq", 5],
                                        "o": "start",
                                        "l": 11,
                                        "c": "Hello world",
                                    }
                                ],
                            }
                        }
                    },
                }
            },
        }

        state = notion_blocks._extract_crdt_title_state(block)
        self.assertEqual(state["text_instance_id"], "text-instance-1")
        self.assertEqual(state["start_id"], ["item-seq", 5])
        self.assertEqual(state["length"], 11)

    def test_extract_crdt_title_state_accepts_fragmented_visible_text(self) -> None:
        block = {
            "properties": {"title": [["Hello world"]]},
            "crdt_data": {
                "title": {
                    "r": "root",
                    "n": {
                        "root": {
                            "s": {
                                "x": "text-instance-2",
                                "i": [
                                    {
                                        "t": "t",
                                        "i": ["item-seq", 5],
                                        "o": "start",
                                        "l": 6,
                                        "c": "Hello ",
                                    },
                                    {
                                        "t": "t",
                                        "i": ["item-seq", 11],
                                        "o": ["item-seq", 10],
                                        "l": 5,
                                        "c": "world",
                                    },
                                ],
                            }
                        }
                    },
                }
            },
        }

        state = notion_blocks._extract_crdt_title_state(block)
        self.assertEqual(state["text_instance_id"], "text-instance-2")
        self.assertEqual(state["start_id"], ["item-seq", 5])
        self.assertEqual(state["length"], 11)
        self.assertEqual(state["runs"][0]["start_offset"], 0)
        self.assertEqual(state["runs"][1]["start_offset"], 6)

    def test_ops_replace_title_text_via_crdt_emits_insert_only_for_append(self) -> None:
        old_block = {
            "properties": {"title": [["Hello world"]]},
            "crdt_data": {
                "title": {
                    "r": "root",
                    "n": {
                        "root": {
                            "s": {
                                "x": "text-instance-1",
                                "i": [
                                    {
                                        "t": "t",
                                        "i": ["item-seq", 5],
                                        "o": "start",
                                        "l": 11,
                                        "c": "Hello world",
                                    }
                                ],
                            }
                        }
                    },
                }
            },
        }

        with mock.patch.object(notion_blocks, "_new_text_item_id", return_value=["new-seq", 1]):
            ops = notion_blocks._ops_replace_title_text_via_crdt(
                "block-1",
                "space-1",
                old_block,
                "Hello world!",
            )

        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0]["command"], "insertText")
        self.assertEqual(ops[0]["args"]["originId"], ["item-seq", 15])
        self.assertEqual(ops[0]["args"]["id"], ["new-seq", 1])
        self.assertEqual(ops[0]["args"]["content"], "!")

    def test_ops_replace_title_text_via_crdt_emits_delete_and_insert_for_middle_change(self) -> None:
        old_block = {
            "properties": {"title": [["Signal Consumed: DR"]]},
            "crdt_data": {
                "title": {
                    "r": "root",
                    "n": {
                        "root": {
                            "s": {
                                "x": "text-instance-3",
                                "i": [
                                    {"t": "t", "i": ["seq", 1], "o": "start", "l": 15, "c": "Signal Consumed"},
                                    {"t": "t", "i": ["seq", 16], "o": ["seq", 15], "l": 2, "c": ": "},
                                    {"t": "t", "i": ["seq", 18], "o": ["seq", 17], "l": 2, "c": "DR"},
                                ],
                            }
                        }
                    },
                }
            },
        }

        with mock.patch.object(notion_blocks, "_new_text_item_id", return_value=["new-seq", 1]):
            ops = notion_blocks._ops_replace_title_text_via_crdt(
                "block-1",
                "space-1",
                old_block,
                "Signal Consumed: DR!",
            )

        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0]["command"], "insertText")
        self.assertEqual(ops[0]["args"]["originId"], ["seq", 19])
        self.assertEqual(ops[0]["args"]["content"], "!")

    def test_ops_update_block_uses_merge_updates(self) -> None:
        ops = notion_blocks._ops_update_block(
            "block-1",
            "space-1",
            {"title": [["Hello world!"]]},
            {"page_icon": "🧪"},
        )

        self.assertEqual(ops[0]["command"], "update")
        self.assertEqual(ops[0]["path"], ["properties"])
        self.assertEqual(ops[1]["command"], "update")
        self.assertEqual(ops[1]["path"], ["format"])

    def test_diff_replace_block_content_preserves_nested_child_ids(self) -> None:
        tree = {
            "recordMap": {
                "block": {
                    "parent": {
                        "value": {
                            "id": "parent",
                            "type": "page",
                            "alive": True,
                            "content": ["header-1"],
                        }
                    },
                    "header-1": {
                        "value": {
                            "id": "header-1",
                            "type": "header",
                            "alive": True,
                            "properties": {"title": [["Overview"]]},
                            "content": ["text-1"],
                        }
                    },
                    "text-1": {
                        "value": {
                            "id": "text-1",
                            "type": "text",
                            "alive": True,
                            "properties": {"title": [["Old body"]]},
                        }
                    },
                }
            }
        }

        new_blocks = [{
            "type": "header",
            "properties": {"title": [["Overview"]]},
            "children": [{
                "type": "text",
                "properties": {"title": [["New body"]]},
            }],
        }]

        with mock.patch.object(notion_blocks, "get_block_tree", return_value=tree), mock.patch.object(
            notion_blocks, "send_ops"
        ) as send_ops:
            stats = notion_blocks.diff_replace_block_content(
                "parent", "space-1", new_blocks, "token", "user-1"
            )

        ops = send_ops.call_args.args[1]
        pointer_ids = [op.get("pointer", {}).get("id") for op in ops]
        self.assertIn("text-1", pointer_ids)
        self.assertNotIn("header-1", [
            op.get("pointer", {}).get("id")
            for op in ops
            if op.get("args", {}).get("alive") is False
        ])
        self.assertNotIn("text-1", [
            op.get("pointer", {}).get("id")
            for op in ops
            if op.get("args", {}).get("alive") is False
        ])
        self.assertEqual(stats["updated"], 2)
        self.assertEqual(stats["inserted"], 0)
        self.assertEqual(stats["deleted"], 0)

    def test_diff_replace_block_content_preserves_later_sibling_ids_after_middle_insert(self) -> None:
        tree = {
            "recordMap": {
                "block": {
                    "parent": {
                        "value": {
                            "id": "parent",
                            "type": "page",
                            "alive": True,
                            "content": ["text-1", "text-2"],
                        }
                    },
                    "text-1": {
                        "value": {
                            "id": "text-1",
                            "type": "text",
                            "alive": True,
                            "properties": {"title": [["First"]]},
                        }
                    },
                    "text-2": {
                        "value": {
                            "id": "text-2",
                            "type": "text",
                            "alive": True,
                            "properties": {"title": [["Second"]]},
                        }
                    },
                }
            }
        }

        new_blocks = [
            {"type": "text", "properties": {"title": [["First"]]}},
            {"type": "text", "properties": {"title": [["Inserted"]]}},
            {"type": "text", "properties": {"title": [["Second"]]}},
        ]

        with mock.patch.object(notion_blocks, "get_block_tree", return_value=tree), mock.patch.object(
            notion_blocks, "send_ops"
        ) as send_ops:
            stats = notion_blocks.diff_replace_block_content(
                "parent", "space-1", new_blocks, "token", "user-1"
            )

        ops = send_ops.call_args.args[1]
        deleted_ids = [
            op.get("pointer", {}).get("id")
            for op in ops
            if op.get("args", {}).get("alive") is False
        ]
        self.assertNotIn("text-1", deleted_ids)
        self.assertNotIn("text-2", deleted_ids)
        insert_ops = [
            op for op in ops
            if op.get("pointer", {}).get("id") == "parent"
            and op.get("path") == ["content"]
        ]
        self.assertTrue(insert_ops)
        self.assertEqual(stats["unchanged"], 2)
        self.assertEqual(stats["inserted"], 1)
        self.assertEqual(stats["deleted"], 0)

    def test_diff_replace_block_content_updates_properties_without_replacing_dict(self) -> None:
        tree = {
            "recordMap": {
                "block": {
                    "parent": {
                        "value": {
                            "id": "parent",
                            "type": "page",
                            "alive": True,
                            "content": ["text-1"],
                        }
                    },
                    "text-1": {
                        "value": {
                            "id": "text-1",
                            "type": "text",
                            "alive": True,
                            "properties": {"title": [["Hello world"]]},
                            "crdt_data": {
                                "title": {
                                    "r": "root",
                                    "n": {
                                        "root": {
                                            "s": {
                                                "x": "text-instance-1",
                                                "i": [
                                                    {
                                                        "t": "t",
                                                        "i": ["item-seq", 5],
                                                        "o": "start",
                                                        "l": 11,
                                                        "c": "Hello world",
                                                    }
                                                ],
                                            }
                                        }
                                    },
                                }
                            },
                        }
                    },
                }
            }
        }

        new_blocks = [
            {"type": "text", "properties": {"title": [["Hello world!"]]}}
        ]

        with mock.patch.object(notion_blocks, "get_block_tree", return_value=tree), mock.patch.object(
            notion_blocks, "send_ops"
        ) as send_ops:
            notion_blocks.diff_replace_block_content(
                "parent", "space-1", new_blocks, "token", "user-1"
            )

        ops = send_ops.call_args.args[1]
        prop_ops = [
            op for op in ops
            if op.get("pointer", {}).get("id") == "text-1"
            and op.get("path") == ["properties"]
        ]
        crdt_delete_ops = [
            op for op in ops
            if op.get("pointer", {}).get("id") == "text-1"
            and op.get("command") == "deleteText"
        ]
        crdt_insert_ops = [
            op for op in ops
            if op.get("pointer", {}).get("id") == "text-1"
            and op.get("command") == "insertText"
        ]
        self.assertEqual(len(prop_ops), 1)
        self.assertEqual(prop_ops[0]["command"], "update")
        self.assertEqual(prop_ops[0]["args"], {"title": [["Hello world!"]]})
        self.assertEqual(len(crdt_delete_ops), 0)
        self.assertEqual(len(crdt_insert_ops), 1)

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

    def test_resolve_render_root_id_follows_multi_hop_copied_chain(self) -> None:
        blocks = {
            "published-wrapper": {
                "value": {
                    "id": "published-wrapper",
                    "type": "page",
                    "alive": True,
                    "format": {
                        "copied_from_pointer": {
                            "id": "draft-wrapper",
                            "table": "block",
                            "spaceId": "space-1",
                        }
                    },
                }
            },
            "draft-wrapper": {
                "value": {
                    "id": "draft-wrapper",
                    "type": "page",
                    "alive": True,
                    "format": {
                        "copied_from_pointer": {
                            "id": "source-root",
                            "table": "block",
                            "spaceId": "space-1",
                        }
                    },
                }
            },
            "source-root": {
                "value": {
                    "id": "source-root",
                    "type": "page",
                    "alive": True,
                }
            },
        }

        self.assertEqual(
            notion_blocks.resolve_render_root_id("published-wrapper", blocks),
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
