import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli"))

import block_builder  # noqa: E402
from block_builder import (  # noqa: E402
    Callout,
    Code,
    Divider,
    Heading,
    ListItem,
    MarkDef,
    MentionSpan,
    Paragraph,
    Quote,
    TextSpan,
    Toggle,
    Unknown,
    normalize_spans,
)


class BlockBuilderIRTests(unittest.TestCase):
    def test_markdown_to_ir_is_sparse(self) -> None:
        md = "\n".join([
            "# Heading",
            "",
            "- hello **world** {{page:12345678-1234-1234-1234-123456789abc}}",
            "  1. nested",
            "> 📌 note",
        ])

        blocks = block_builder.markdown_to_ir(md)

        self.assertIsInstance(blocks[0], Heading)
        self.assertEqual(blocks[0].level, 1)
        self.assertIsInstance(blocks[1], ListItem)
        self.assertEqual(blocks[1].list_kind, "bulleted")

        spans = blocks[1].spans
        self.assertEqual(spans[0], TextSpan(text="hello "))
        self.assertEqual(spans[1], TextSpan(text="world", marks=["bold"]))
        # After normalization, trailing space + mention are separate spans
        self.assertEqual(spans[2], TextSpan(text=" "))
        self.assertEqual(
            spans[3],
            MentionSpan(kind="page", id="12345678-1234-1234-1234-123456789abc"),
        )

        nested = blocks[1].children[0]
        self.assertIsInstance(nested, ListItem)
        self.assertEqual(nested.list_kind, "numbered")

    def test_sparse_serialization(self) -> None:
        """model_dump(exclude_defaults=True) produces sparse dicts."""
        span = TextSpan(text="hello")
        dumped = span.model_dump(exclude_defaults=True)
        self.assertNotIn("marks", dumped)
        self.assertEqual(dumped["text"], "hello")

        span_bold = TextSpan(text="world", marks=["bold"])
        dumped = span_bold.model_dump(exclude_defaults=True)
        self.assertEqual(dumped["marks"], ["bold"])

        mention = MentionSpan(kind="page", id="abc-123")
        dumped = mention.model_dump(exclude_defaults=True)
        self.assertEqual(dumped["kind"], "page")

        para = Paragraph(spans=[span])
        dumped = para.model_dump(exclude_defaults=True)
        self.assertNotIn("children", dumped)
        self.assertNotIn("properties", dumped)
        self.assertNotIn("mark_defs", dumped)

        callout = Callout(spans=[span])
        dumped = callout.model_dump(exclude_defaults=True)
        self.assertNotIn("icon", dumped)

        callout_custom = Callout(spans=[span], icon="🔥")
        dumped = callout_custom.model_dump(exclude_defaults=True)
        self.assertEqual(dumped["icon"], "🔥")

    def test_type_validation(self) -> None:
        """Pydantic enforces field types and valid enum values."""
        h = Heading(level=2, spans=[TextSpan(text="ok")])
        self.assertEqual(h.level, 2)

        with self.assertRaises(Exception):
            Heading(level=5, spans=[TextSpan(text="bad")])

        with self.assertRaises(Exception):
            MentionSpan(kind="invalid", id="abc")

    def test_ir_round_trip_through_notion_blocks(self) -> None:
        md = "\n".join([
            "## Hello",
            "- item",
            "  - nested `code`",
            "> 📌 note",
            "```py",
            "print('hi')",
            "```",
            "---",
        ])

        ir_blocks = block_builder.markdown_to_ir(md)
        notion_blocks = block_builder.ir_to_notion_blocks(ir_blocks)

        root_id = "root"
        blocks_map = {
            root_id: {"value": {"content": []}},
        }

        counter = 0

        def add_block(parent_id: str, block: dict) -> None:
            nonlocal counter
            counter += 1
            block_id = f"block-{counter}"
            blocks_map[root_id if parent_id == root_id else parent_id]["value"].setdefault("content", []).append(block_id)
            value = {**block, "id": block_id}
            children = value.pop("children", None)
            blocks_map[block_id] = {"value": value}
            if children:
                blocks_map[block_id]["value"]["content"] = []
                for child in children:
                    add_block(block_id, child)

        for notion_block in notion_blocks:
            add_block(root_id, notion_block)

        rebuilt_ir = block_builder.notion_blocks_to_ir(blocks_map, root_id)
        rebuilt_md = block_builder.blocks_to_markdown(blocks_map, root_id)

        self.assertEqual(rebuilt_ir, ir_blocks)
        self.assertEqual(rebuilt_md, md)

    def test_all_block_types_construct(self) -> None:
        """Every IR block type can be constructed and round-trips."""
        spans = [TextSpan(text="hello")]
        blocks = [
            Paragraph(spans=spans),
            Heading(level=1, spans=spans),
            Heading(level=2, spans=spans),
            Heading(level=3, spans=spans),
            ListItem(list_kind="bulleted", spans=spans),
            ListItem(list_kind="numbered", spans=spans),
            Callout(spans=spans),
            Callout(spans=spans, icon="🔥"),
            Code(text="x = 1", language="python"),
            Code(text="plain"),
            Divider(),
        ]
        md = block_builder.ir_to_markdown(blocks)
        rebuilt = block_builder.markdown_to_ir(md)
        self.assertEqual(len(rebuilt), len(blocks))

    def test_nested_children(self) -> None:
        """Children are properly typed model instances."""
        child = ListItem(list_kind="numbered", spans=[TextSpan(text="sub")])
        parent = ListItem(list_kind="bulleted", spans=[TextSpan(text="top")], children=[child])

        self.assertIsInstance(parent.children[0], ListItem)
        self.assertEqual(parent.children[0].list_kind, "numbered")

        dumped = parent.model_dump(exclude_defaults=True)
        self.assertNotIn("children", dumped["children"][0])


class NormalizeSpansTests(unittest.TestCase):
    def test_merge_adjacent_same_marks(self) -> None:
        """Adjacent TextSpans with identical marks are merged."""
        spans = [
            TextSpan(text="hello "),
            TextSpan(text="world"),
        ]
        result = normalize_spans(spans)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "hello world")

    def test_no_merge_different_marks(self) -> None:
        """Adjacent TextSpans with different marks stay separate."""
        spans = [
            TextSpan(text="hello ", marks=["bold"]),
            TextSpan(text="world"),
        ]
        result = normalize_spans(spans)
        self.assertEqual(len(result), 2)

    def test_drop_empty_spans(self) -> None:
        """Empty text spans are removed."""
        spans = [
            TextSpan(text=""),
            TextSpan(text="hello"),
            TextSpan(text=""),
        ]
        result = normalize_spans(spans)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "hello")

    def test_empty_input_returns_empty_span(self) -> None:
        """Empty input produces a single empty text span."""
        self.assertEqual(normalize_spans([]), [TextSpan(text="")])
        self.assertEqual(
            normalize_spans([TextSpan(text="")]),
            [TextSpan(text="")],
        )

    def test_mentions_not_merged(self) -> None:
        """MentionSpans are never merged with adjacent text."""
        spans = [
            TextSpan(text="see "),
            MentionSpan(kind="page", id="abc"),
            TextSpan(text=" here"),
        ]
        result = normalize_spans(spans)
        self.assertEqual(len(result), 3)

    def test_merge_with_marks(self) -> None:
        """Adjacent bold spans merge into one bold span."""
        spans = [
            TextSpan(text="hello ", marks=["bold"]),
            TextSpan(text="world", marks=["bold"]),
        ]
        result = normalize_spans(spans)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "hello world")
        self.assertEqual(result[0].marks, ["bold"])

    def test_merge_chain(self) -> None:
        """Multiple adjacent same-mark spans merge into one."""
        spans = [TextSpan(text="a"), TextSpan(text="b"), TextSpan(text="c")]
        result = normalize_spans(spans)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "abc")


class MarkDefTests(unittest.TestCase):
    def test_link_markdown_round_trip(self) -> None:
        """[text](url) in markdown creates a markDef and round-trips."""
        md = "click [here](https://example.com) now"
        blocks = block_builder.markdown_to_ir(md)
        self.assertEqual(len(blocks), 1)
        para = blocks[0]
        self.assertIsInstance(para, Paragraph)

        # Should have a link markDef
        self.assertEqual(len(para.mark_defs), 1)
        self.assertEqual(para.mark_defs[0].mark_type, "link")
        self.assertEqual(para.mark_defs[0].href, "https://example.com")

        # The "here" span should reference the markDef key
        link_key = para.mark_defs[0].key
        link_span = next(s for s in para.spans if isinstance(s, TextSpan) and link_key in s.marks)
        self.assertEqual(link_span.text, "here")

        # Round-trip back to markdown
        rebuilt_md = block_builder.ir_to_markdown(blocks)
        self.assertEqual(rebuilt_md, md)

    def test_strikethrough_markdown(self) -> None:
        """~~text~~ creates a strikethrough mark."""
        md = "this is ~~deleted~~ text"
        blocks = block_builder.markdown_to_ir(md)
        para = blocks[0]
        strike_span = next(
            s for s in para.spans
            if isinstance(s, TextSpan) and "strikethrough" in s.marks
        )
        self.assertEqual(strike_span.text, "deleted")

        rebuilt_md = block_builder.ir_to_markdown(blocks)
        self.assertEqual(rebuilt_md, md)

    def test_link_notion_round_trip(self) -> None:
        """Notion link annotation ["a", url] hoists to markDef and back."""
        # Simulate Notion rich text with a link annotation.
        notion_segments = [
            ["click "],
            ["here", [["a", "https://example.com"]]],
            [" now"],
        ]
        spans, mark_defs = block_builder._notion_rich_text_to_spans(notion_segments)

        self.assertEqual(len(mark_defs), 1)
        self.assertEqual(mark_defs[0].mark_type, "link")
        self.assertEqual(mark_defs[0].href, "https://example.com")

        # The link span references the markDef key
        link_key = mark_defs[0].key
        link_span = next(s for s in spans if isinstance(s, TextSpan) and link_key in s.marks)
        self.assertEqual(link_span.text, "here")

        # Convert back to Notion rich text
        rebuilt = block_builder._spans_to_notion_rich_text(spans, mark_defs)
        # The link annotation should be restored
        link_seg = next(seg for seg in rebuilt if len(seg) > 1 and any(
            isinstance(a, list) and a[0] == "a" for a in seg[1]
        ))
        self.assertEqual(link_seg[0], "here")
        link_ann = next(a for a in link_seg[1] if a[0] == "a")
        self.assertEqual(link_ann[1], "https://example.com")

    def test_color_notion_round_trip(self) -> None:
        """Notion color annotation ["h", color] hoists to markDef and back."""
        notion_segments = [
            ["red text", [["h", "red"]]],
        ]
        spans, mark_defs = block_builder._notion_rich_text_to_spans(notion_segments)

        self.assertEqual(len(mark_defs), 1)
        self.assertEqual(mark_defs[0].mark_type, "color")
        self.assertEqual(mark_defs[0].value, "red")

        rebuilt = block_builder._spans_to_notion_rich_text(spans, mark_defs)
        self.assertEqual(rebuilt[0][0], "red text")
        color_ann = next(a for a in rebuilt[0][1] if a[0] == "h")
        self.assertEqual(color_ann[1], "red")

    def test_bold_link_combined(self) -> None:
        """A span can have both decorator marks and markDef references."""
        notion_segments = [
            ["bold link", [["b"], ["a", "https://example.com"]]],
        ]
        spans, mark_defs = block_builder._notion_rich_text_to_spans(notion_segments)

        self.assertEqual(len(mark_defs), 1)
        span = spans[0]
        self.assertIsInstance(span, TextSpan)
        self.assertIn("bold", span.marks)
        self.assertIn(mark_defs[0].key, span.marks)

    def test_mark_defs_excluded_when_empty(self) -> None:
        """mark_defs field is excluded from sparse serialization when empty."""
        para = Paragraph(spans=[TextSpan(text="no links")])
        dumped = para.model_dump(exclude_defaults=True)
        self.assertNotIn("mark_defs", dumped)

    def test_mark_defs_present_when_populated(self) -> None:
        """mark_defs field appears in serialization when non-empty."""
        md = MarkDef(key="k1", mark_type="link", href="https://x.com")
        para = Paragraph(
            spans=[TextSpan(text="link", marks=["k1"])],
            mark_defs=[md],
        )
        dumped = para.model_dump(exclude_defaults=True)
        self.assertIn("mark_defs", dumped)
        self.assertEqual(len(dumped["mark_defs"]), 1)

    def test_multiple_links_in_one_block(self) -> None:
        """Multiple links in one line get separate markDefs."""
        md = "[a](https://a.com) and [b](https://b.com)"
        blocks = block_builder.markdown_to_ir(md)
        para = blocks[0]
        self.assertEqual(len(para.mark_defs), 2)
        self.assertNotEqual(para.mark_defs[0].key, para.mark_defs[1].key)
        self.assertEqual(para.mark_defs[0].href, "https://a.com")
        self.assertEqual(para.mark_defs[1].href, "https://b.com")


class StrikethroughNotionTests(unittest.TestCase):
    def test_strikethrough_notion_round_trip(self) -> None:
        """Notion strikethrough annotation ["s"] round-trips through IR."""
        notion_segments = [
            ["deleted", [["s"]]],
        ]
        spans, mark_defs = block_builder._notion_rich_text_to_spans(notion_segments)
        self.assertEqual(len(mark_defs), 0)
        self.assertIn("strikethrough", spans[0].marks)

        rebuilt = block_builder._spans_to_notion_rich_text(spans, mark_defs)
        self.assertEqual(rebuilt[0][0], "deleted")
        self.assertIn(["s"], rebuilt[0][1])

    def test_underline_notion_round_trip(self) -> None:
        """Notion underline annotation ["_"] round-trips through IR."""
        notion_segments = [
            ["underlined", [["_"]]],
        ]
        spans, mark_defs = block_builder._notion_rich_text_to_spans(notion_segments)
        self.assertIn("underline", spans[0].marks)

        rebuilt = block_builder._spans_to_notion_rich_text(spans, mark_defs)
        self.assertIn(["_"], rebuilt[0][1])


class QuoteBlockTests(unittest.TestCase):
    def test_quote_from_notion(self) -> None:
        """Notion 'quote' block type maps to Quote IR block."""
        blocks_map = {
            "root": {"value": {"content": ["q1"]}},
            "q1": {"value": {"type": "quote", "properties": {"title": [["quoted text"]]}}},
        }
        ir = block_builder.notion_blocks_to_ir(blocks_map, "root")
        self.assertEqual(len(ir), 1)
        self.assertIsInstance(ir[0], Quote)
        self.assertEqual(ir[0].spans[0].text, "quoted text")

    def test_quote_to_notion(self) -> None:
        """Quote IR block emits Notion 'quote' type."""
        q = Quote(spans=[TextSpan(text="hello")])
        notion = block_builder._ir_block_to_notion(q)
        self.assertEqual(notion["type"], "quote")
        self.assertEqual(notion["properties"]["title"][0][0], "hello")

    def test_quote_to_markdown(self) -> None:
        """Quote block emits '> text' without icon (unlike Callout)."""
        q = Quote(spans=[TextSpan(text="wise words")])
        md = block_builder.ir_to_markdown([q])
        self.assertEqual(md, "> wise words")

    def test_quote_notion_round_trip(self) -> None:
        """Quote survives Notion → IR → Notion round-trip."""
        q = Quote(spans=[TextSpan(text="hello")])
        notion = block_builder._ir_block_to_notion(q)

        blocks_map = {
            "root": {"value": {"content": ["b1"]}},
            "b1": {"value": {**notion, "id": "b1"}},
        }
        rebuilt = block_builder.notion_blocks_to_ir(blocks_map, "root")
        self.assertEqual(rebuilt[0], q)


class ToggleBlockTests(unittest.TestCase):
    def test_toggle_from_notion(self) -> None:
        """Notion 'toggle_list' block type maps to Toggle IR block."""
        blocks_map = {
            "root": {"value": {"content": ["t1"]}},
            "t1": {"value": {
                "type": "toggle_list",
                "properties": {"title": [["Toggle header"]]},
                "content": ["c1"],
            }},
            "c1": {"value": {"type": "text", "properties": {"title": [["Hidden content"]]}}},
        }
        ir = block_builder.notion_blocks_to_ir(blocks_map, "root")
        self.assertEqual(len(ir), 1)
        self.assertIsInstance(ir[0], Toggle)
        self.assertEqual(ir[0].spans[0].text, "Toggle header")
        self.assertEqual(len(ir[0].children), 1)
        self.assertIsInstance(ir[0].children[0], Paragraph)

    def test_toggle_to_notion(self) -> None:
        """Toggle IR block emits Notion 'toggle_list' type."""
        t = Toggle(
            spans=[TextSpan(text="Summary")],
            children=[Paragraph(spans=[TextSpan(text="Details")])],
        )
        notion = block_builder._ir_block_to_notion(t)
        self.assertEqual(notion["type"], "toggle_list")
        self.assertEqual(len(notion["children"]), 1)

    def test_toggle_to_markdown(self) -> None:
        """Toggle emits <details>/<summary> HTML."""
        t = Toggle(
            spans=[TextSpan(text="Click me")],
            children=[Paragraph(spans=[TextSpan(text="Hidden")])],
        )
        md = block_builder.ir_to_markdown([t])
        self.assertIn("<details>", md)
        self.assertIn("<summary>Click me</summary>", md)
        self.assertIn("Hidden", md)
        self.assertIn("</details>", md)

    def test_toggle_notion_round_trip(self) -> None:
        """Toggle with children survives Notion → IR → Notion."""
        t = Toggle(
            spans=[TextSpan(text="Title")],
            children=[Paragraph(spans=[TextSpan(text="Body")])],
        )
        notion = block_builder._ir_block_to_notion(t)

        # Build blocks_map
        blocks_map = {
            "root": {"value": {"content": ["t1"]}},
            "t1": {"value": {
                **{k: v for k, v in notion.items() if k != "children"},
                "id": "t1",
                "content": ["c1"],
            }},
            "c1": {"value": {**notion["children"][0], "id": "c1"}},
        }
        rebuilt = block_builder.notion_blocks_to_ir(blocks_map, "root")
        self.assertEqual(rebuilt[0], t)


class UnknownBlockTests(unittest.TestCase):
    def test_unknown_from_notion(self) -> None:
        """Unrecognized Notion block type becomes Unknown with raw data preserved."""
        blocks_map = {
            "root": {"value": {"content": ["u1"]}},
            "u1": {"value": {
                "type": "table_of_contents",
                "properties": {"title": [["TOC"]]},
                "format": {"block_color": "gray"},
            }},
        }
        ir = block_builder.notion_blocks_to_ir(blocks_map, "root")
        self.assertEqual(len(ir), 1)
        self.assertIsInstance(ir[0], Unknown)
        self.assertEqual(ir[0].notion_type, "table_of_contents")
        self.assertEqual(ir[0].raw_format, {"block_color": "gray"})

    def test_unknown_round_trip_to_notion(self) -> None:
        """Unknown block reconstructs the original Notion type and format."""
        u = Unknown(
            notion_type="table_of_contents",
            spans=[TextSpan(text="TOC")],
            raw_properties={"some_prop": [["val"]]},
            raw_format={"block_color": "gray"},
        )
        notion = block_builder._ir_block_to_notion(u)
        self.assertEqual(notion["type"], "table_of_contents")
        self.assertEqual(notion["format"], {"block_color": "gray"})
        # title comes from spans, other props preserved
        self.assertIn("some_prop", notion["properties"])

    def test_unknown_to_markdown(self) -> None:
        """Unknown block emits HTML comment with type + text content."""
        u = Unknown(
            notion_type="bookmark",
            spans=[TextSpan(text="https://example.com")],
        )
        md = block_builder.ir_to_markdown([u])
        self.assertIn("<!-- notion:bookmark -->", md)
        self.assertIn("https://example.com", md)

    def test_unknown_sparse_serialization(self) -> None:
        """Unknown block excludes empty raw_properties and raw_format."""
        u = Unknown(notion_type="embed", spans=[TextSpan(text="x")])
        dumped = u.model_dump(exclude_defaults=True)
        self.assertNotIn("raw_properties", dumped)
        self.assertNotIn("raw_format", dumped)
        self.assertEqual(dumped["notion_type"], "embed")

    def test_paragraph_still_works(self) -> None:
        """Standard 'text' type still maps to Paragraph, not Unknown."""
        blocks_map = {
            "root": {"value": {"content": ["p1"]}},
            "p1": {"value": {"type": "text", "properties": {"title": [["hello"]]}}},
        }
        ir = block_builder.notion_blocks_to_ir(blocks_map, "root")
        self.assertIsInstance(ir[0], Paragraph)


if __name__ == "__main__":
    unittest.main()
