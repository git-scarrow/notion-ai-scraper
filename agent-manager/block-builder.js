// block-builder.js — Markdown ↔ compact IR ↔ Notion block conversion.
// Used in the extension page to keep Notion-shaped payloads at the edge only.
//
// IR schema contract (must match Python Pydantic models in cli/block_builder.py):
//
// IRSpan = TextSpan | MentionSpan
//   TextSpan:    { type: "text", text: string, marks?: string[] }
//     marks contains decorator names ("bold","italic","code","strikethrough","underline")
//     and/or keys referencing MarkDef entries on the parent block.
//   MentionSpan: { type: "mention", kind: "page"|"user"|"date"|"agent"|"space", id: string }
//
// MarkDef = { key: string, mark_type: string, href?: string, value?: string }
//   mark_type "link": href is the URL
//   mark_type "color": value is the color name
//
// IRBlock = Paragraph | Heading | ListItem | Callout | Quote | Toggle | Code | Divider | Unknown
//   Paragraph: { type: "paragraph", spans: IRSpan[], mark_defs?: MarkDef[], children?: IRBlock[] }
//   Heading:   { type: "heading", level: 1|2|3, spans: IRSpan[], mark_defs?: MarkDef[], children?: IRBlock[] }
//   ListItem:  { type: "list_item", list_kind: "bulleted"|"numbered", spans: IRSpan[], mark_defs?: MarkDef[], children?: IRBlock[] }
//   Callout:   { type: "callout", spans: IRSpan[], icon?: string, mark_defs?: MarkDef[], children?: IRBlock[] }
//   Quote:     { type: "quote", spans: IRSpan[], mark_defs?: MarkDef[], children?: IRBlock[] }
//   Toggle:    { type: "toggle", spans: IRSpan[], mark_defs?: MarkDef[], children?: IRBlock[] }
//   Code:      { type: "code", text: string, language?: string, children?: IRBlock[] }
//   Divider:   { type: "divider", children?: IRBlock[] }
//   Unknown:   { type: "unknown", notion_type: string, spans?: IRSpan[], mark_defs?: MarkDef[], raw_properties?: object, raw_format?: object, children?: IRBlock[] }

// Mention type codes used by Notion rich text annotations.
const MENTION_TYPES = { p: 'page', u: 'user', d: 'date', a: 'agent', s: 'space' };
const MENTION_CODES = Object.fromEntries(Object.entries(MENTION_TYPES).map(([k, v]) => [v, k]));

const MARK_TO_ANNOTATION = { bold: 'b', italic: 'i', code: 'c', strikethrough: 's', underline: '_' };
const ANNOTATION_TO_MARK = Object.fromEntries(Object.entries(MARK_TO_ANNOTATION).map(([k, v]) => [v, k]));
const MARK_ORDER = ['bold', 'italic', 'code', 'strikethrough', 'underline'];
const DECORATOR_NAMES = new Set(MARK_ORDER);

function textSpan(text, ...marks) {
  const ordered = MARK_ORDER.filter(mark => marks.includes(mark));
  // Append non-decorator marks (markDef keys) in original order.
  for (const m of marks) {
    if (!DECORATOR_NAMES.has(m)) ordered.push(m);
  }
  const span = { type: 'text', text };
  if (ordered.length) span.marks = ordered;
  return span;
}

function mentionSpan(kind, id) {
  return { type: 'mention', kind, id };
}

function block(type, extra = {}) {
  return { type, ...extra };
}

// ---------------------------------------------------------------------------
// Span normalization (ProseMirror pattern)
// ---------------------------------------------------------------------------

function normalizeSpans(spans) {
  if (!spans.length) return [{ type: 'text', text: '' }];
  const result = [];
  for (const span of spans) {
    // Drop empty text spans.
    if (span.type === 'text' && !span.text) continue;
    // Merge adjacent TextSpans with identical marks.
    const prev = result[result.length - 1];
    if (
      prev &&
      span.type === 'text' &&
      prev.type === 'text' &&
      arraysEqual(span.marks || [], prev.marks || [])
    ) {
      const merged = { type: 'text', text: prev.text + span.text };
      if (prev.marks?.length) merged.marks = [...prev.marks];
      result[result.length - 1] = merged;
      continue;
    }
    result.push(span);
  }
  return result.length ? result : [{ type: 'text', text: '' }];
}

function arraysEqual(a, b) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

// ---------------------------------------------------------------------------
// Inline markdown → spans
// ---------------------------------------------------------------------------

const FMT_RE = /\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`|~~(.+?)~~|\[([^\]]+)\]\(([^)]+)\)|([^*`~[]+)/g;

function markdownToSpans(text) {
  const spans = [];
  const markDefs = [];
  let linkCounter = 0;
  const parts = text.split(/(\{\{\w+:[0-9a-f-]+\}\})/g);
  for (const part of parts) {
    if (!part) continue;
    const mentionMatch = /^\{\{(\w+):([0-9a-f-]+)\}\}$/.exec(part);
    if (mentionMatch) {
      spans.push(mentionSpan(mentionMatch[1], mentionMatch[2]));
      continue;
    }

    FMT_RE.lastIndex = 0;
    let match;
    while ((match = FMT_RE.exec(part)) !== null) {
      const [, bold, italic, inlineCode, strike, linkText, linkUrl, plain] = match;
      if (bold) spans.push(textSpan(bold, 'bold'));
      else if (italic) spans.push(textSpan(italic, 'italic'));
      else if (inlineCode) spans.push(textSpan(inlineCode, 'code'));
      else if (strike) spans.push(textSpan(strike, 'strikethrough'));
      else if (linkText && linkUrl) {
        const key = `_link-${linkCounter++}`;
        markDefs.push({ key, mark_type: 'link', href: linkUrl });
        spans.push(textSpan(linkText, key));
      } else if (plain) spans.push(textSpan(plain));
    }
  }
  const normalized = spans.length ? normalizeSpans(spans) : [textSpan(text)];
  return { spans: normalized, markDefs };
}

// ---------------------------------------------------------------------------
// Notion rich text ↔ spans
// ---------------------------------------------------------------------------

function notionRichTextToSpans(segments) {
  const spans = [];
  const markDefs = [];
  let linkCounter = 0;
  let colorCounter = 0;

  for (const seg of segments) {
    const text = seg?.[0] ?? '';
    const annotations = seg?.[1] ?? [];

    if (text === '\u2023') {
      const mention = annotations.find(a => Array.isArray(a) && a.length >= 2);
      if (mention) spans.push(mentionSpan(MENTION_TYPES[mention[0]] || mention[0], mention[1]));
      else spans.push(textSpan(text));
      continue;
    }

    const marks = [];
    for (const annotation of annotations) {
      if (!Array.isArray(annotation) || !annotation.length) continue;
      const code = annotation[0];
      if (ANNOTATION_TO_MARK[code]) {
        marks.push(ANNOTATION_TO_MARK[code]);
      } else if (code === 'a' && annotation.length >= 2) {
        const key = `_link-${linkCounter++}`;
        markDefs.push({ key, mark_type: 'link', href: annotation[1] });
        marks.push(key);
      } else if (code === 'h' && annotation.length >= 2) {
        const key = `_color-${colorCounter++}`;
        markDefs.push({ key, mark_type: 'color', value: annotation[1] });
        marks.push(key);
      }
    }
    spans.push(textSpan(text, ...marks));
  }
  return { spans: normalizeSpans(spans), markDefs };
}

function spansToRichText(spans, markDefs = []) {
  const defsByKey = Object.fromEntries(markDefs.map(md => [md.key, md]));
  const richText = [];
  for (const span of spans) {
    if (span.type === 'mention') {
      richText.push(['\u2023', [[MENTION_CODES[span.kind] || span.kind, span.id]]]);
      continue;
    }

    const chunk = [span.text];
    const notionMarks = [];
    for (const mark of (span.marks || [])) {
      if (MARK_TO_ANNOTATION[mark]) {
        notionMarks.push([MARK_TO_ANNOTATION[mark]]);
      } else if (defsByKey[mark]) {
        const md = defsByKey[mark];
        if (md.mark_type === 'link') notionMarks.push(['a', md.href]);
        else if (md.mark_type === 'color') notionMarks.push(['h', md.value]);
      }
    }
    if (notionMarks.length) chunk.push(notionMarks);
    richText.push(chunk);
  }
  return richText.length ? richText : [['']];
}

function spansToMarkdown(spans, markDefs = []) {
  const defsByKey = Object.fromEntries(markDefs.map(md => [md.key, md]));
  return spans.map(span => {
    if (span.type === 'mention') return `{{${span.kind}:${span.id}}}`;

    const marks = new Set(span.marks || []);
    let out = span.text;
    if (marks.has('code')) out = `\`${out}\``;
    if (marks.has('strikethrough')) out = `~~${out}~~`;
    if (marks.has('italic')) out = `*${out}*`;
    if (marks.has('bold')) out = `**${out}**`;

    // Wrap in link if a link markDef is referenced.
    const linkMark = (span.marks || []).find(m => defsByKey[m]?.mark_type === 'link');
    if (linkMark) out = `[${out}](${defsByKey[linkMark].href})`;

    return out;
  }).join('');
}

// ---------------------------------------------------------------------------
// IR → Notion blocks
// ---------------------------------------------------------------------------

function irBlockToNotion(blockNode) {
  let notionBlock;
  const markDefs = blockNode.mark_defs || [];

  if (blockNode.type === 'divider') {
    notionBlock = { type: 'divider', properties: {} };
  } else if (blockNode.type === 'code') {
    notionBlock = {
      type: 'code',
      properties: {
        title: [[blockNode.text]],
        language: [[blockNode.language || 'plain text']],
      },
    };
  } else if (blockNode.type === 'heading') {
    const notionType = { 1: 'header', 2: 'sub_header', 3: 'sub_sub_header' }[blockNode.level] || 'sub_sub_header';
    notionBlock = { type: notionType, properties: { title: spansToRichText(blockNode.spans, markDefs) } };
  } else if (blockNode.type === 'list_item') {
    const notionType = blockNode.list_kind === 'numbered' ? 'numbered_list' : 'bulleted_list';
    notionBlock = { type: notionType, properties: { title: spansToRichText(blockNode.spans, markDefs) } };
  } else if (blockNode.type === 'callout') {
    notionBlock = {
      type: 'callout',
      properties: { title: spansToRichText(blockNode.spans, markDefs) },
      format: { page_icon: blockNode.icon || '📌' },
    };
  } else if (blockNode.type === 'quote') {
    notionBlock = { type: 'quote', properties: { title: spansToRichText(blockNode.spans, markDefs) } };
  } else if (blockNode.type === 'toggle') {
    notionBlock = { type: 'toggle', properties: { title: spansToRichText(blockNode.spans, markDefs) } };
  } else if (blockNode.type === 'unknown') {
    const props = { ...(blockNode.raw_properties || {}) };
    if (blockNode.spans?.length) props.title = spansToRichText(blockNode.spans, markDefs);
    notionBlock = { type: blockNode.notion_type, properties: props };
    if (blockNode.raw_format && Object.keys(blockNode.raw_format).length) {
      notionBlock.format = blockNode.raw_format;
    }
  } else {
    notionBlock = { type: 'text', properties: { title: spansToRichText(blockNode.spans, markDefs) } };
  }

  if (blockNode.children?.length) {
    notionBlock.children = blockNode.children.map(irBlockToNotion);
  }
  return notionBlock;
}

// ---------------------------------------------------------------------------
// Notion blocks → IR
// ---------------------------------------------------------------------------

function notionBlockToIr(blockNode, blocksMap) {
  const type = blockNode.type || 'text';
  const properties = blockNode.properties || {};
  const { spans: titleSpans, markDefs } = notionRichTextToSpans(properties.title || []);

  let irBlock;
  if (type === 'header') {
    irBlock = block('heading', { level: 1, spans: titleSpans, mark_defs: markDefs });
  } else if (type === 'sub_header') {
    irBlock = block('heading', { level: 2, spans: titleSpans, mark_defs: markDefs });
  } else if (type === 'sub_sub_header') {
    irBlock = block('heading', { level: 3, spans: titleSpans, mark_defs: markDefs });
  } else if (type === 'bulleted_list') {
    irBlock = block('list_item', { list_kind: 'bulleted', spans: titleSpans, mark_defs: markDefs });
  } else if (type === 'numbered_list') {
    irBlock = block('list_item', { list_kind: 'numbered', spans: titleSpans, mark_defs: markDefs });
  } else if (type === 'callout') {
    irBlock = block('callout', {
      spans: titleSpans,
      mark_defs: markDefs,
      icon: blockNode.format?.page_icon || '📌',
    });
  } else if (type === 'code') {
    const language = properties.language?.[0]?.[0] || 'plain text';
    const text = properties.title?.[0]?.[0] || '';
    irBlock = block('code', { text, language });
  } else if (type === 'quote') {
    irBlock = block('quote', { spans: titleSpans, mark_defs: markDefs });
  } else if (type === 'toggle') {
    irBlock = block('toggle', { spans: titleSpans, mark_defs: markDefs });
  } else if (type === 'divider') {
    irBlock = block('divider');
  } else if (type === 'text' || type === '') {
    irBlock = block('paragraph', { spans: titleSpans, mark_defs: markDefs });
  } else {
    const rawProps = { ...properties };
    delete rawProps.title;
    irBlock = block('unknown', {
      notion_type: type,
      spans: titleSpans,
      mark_defs: markDefs,
      raw_properties: rawProps,
      raw_format: blockNode.format || {},
    });
  }

  if (blockNode.content?.length) {
    const children = blockNode.content
      .map(id => blocksMap[id]?.value)
      .filter(child => child && child.alive !== false)
      .map(child => notionBlockToIr(child, blocksMap));
    if (children.length) irBlock.children = children;
  }
  return irBlock;
}

// ---------------------------------------------------------------------------
// Markdown → IR blocks
// ---------------------------------------------------------------------------

function parseLineToIr(line) {
  let match;
  if ((match = /^### (.+)/.exec(line))) {
    const { spans, markDefs } = markdownToSpans(match[1]);
    return block('heading', { level: 3, spans, mark_defs: markDefs });
  }
  if ((match = /^## (.+)/.exec(line))) {
    const { spans, markDefs } = markdownToSpans(match[1]);
    return block('heading', { level: 2, spans, mark_defs: markDefs });
  }
  if ((match = /^# (.+)/.exec(line))) {
    const { spans, markDefs } = markdownToSpans(match[1]);
    return block('heading', { level: 1, spans, mark_defs: markDefs });
  }
  if (/^[-*_]{3,}$/.test(line)) return block('divider');
  if (line.startsWith('>')) {
    const text = line.replace(/^>\s*/, '');
    const icon = /^(\p{Emoji_Presentation}|\p{Extended_Pictographic})\s*(.*)/u.exec(text);
    if (icon) {
      const { spans, markDefs } = markdownToSpans(icon[2]);
      return block('callout', { icon: icon[1], spans, mark_defs: markDefs });
    }
    const { spans, markDefs } = markdownToSpans(text);
    return block('callout', { icon: '📌', spans, mark_defs: markDefs });
  }
  if (/^[-*+] /.test(line)) {
    const { spans, markDefs } = markdownToSpans(line.replace(/^[-*+] /, ''));
    return block('list_item', { list_kind: 'bulleted', spans, mark_defs: markDefs });
  }
  if (/^\d+\. /.test(line)) {
    const { spans, markDefs } = markdownToSpans(line.replace(/^\d+\. /, ''));
    return block('list_item', { list_kind: 'numbered', spans, mark_defs: markDefs });
  }
  const { spans, markDefs } = markdownToSpans(line);
  return block('paragraph', { spans, mark_defs: markDefs });
}

function appendBlock(blocks, indent, blockNode) {
  if (indent > 0 && blocks.length > 0) {
    let parent = blocks[blocks.length - 1];
    for (let depth = 1; depth < indent; depth++) {
      if (parent.children?.length) parent = parent.children[parent.children.length - 1];
      else break;
    }
    if (!parent.children) parent.children = [];
    parent.children.push(blockNode);
    return;
  }
  blocks.push(blockNode);
}

// ---------------------------------------------------------------------------
// IR → Markdown
// ---------------------------------------------------------------------------

function irBlockToMarkdownLines(blockNode, indent = 0) {
  const prefix = '  '.repeat(indent);
  const lines = [];
  const markDefs = blockNode.mark_defs || [];

  if (blockNode.type === 'heading') {
    const hashes = '#'.repeat(Math.min(Math.max(blockNode.level || 3, 1), 3));
    lines.push(`${prefix}${hashes} ${spansToMarkdown(blockNode.spans, markDefs)}`);
  } else if (blockNode.type === 'list_item') {
    const marker = blockNode.list_kind === 'numbered' ? '1.' : '-';
    lines.push(`${prefix}${marker} ${spansToMarkdown(blockNode.spans, markDefs)}`);
  } else if (blockNode.type === 'callout') {
    lines.push(`${prefix}> ${blockNode.icon || '📌'} ${spansToMarkdown(blockNode.spans, markDefs)}`.trimEnd());
  } else if (blockNode.type === 'quote') {
    lines.push(`${prefix}> ${spansToMarkdown(blockNode.spans, markDefs)}`.trimEnd());
  } else if (blockNode.type === 'toggle') {
    lines.push(`${prefix}<details>`);
    lines.push(`${prefix}<summary>${spansToMarkdown(blockNode.spans, markDefs)}</summary>`);
  } else if (blockNode.type === 'code') {
    lines.push(`${prefix}\`\`\`${blockNode.language || 'plain text'}`);
    lines.push(blockNode.text || '');
    lines.push(`${prefix}\`\`\``);
  } else if (blockNode.type === 'divider') {
    lines.push(`${prefix}---`);
  } else if (blockNode.type === 'unknown') {
    lines.push(`${prefix}<!-- unknown notion block: ${blockNode.notion_type} -->`);
    if (blockNode.spans?.length) {
      lines.push(`${prefix}${spansToMarkdown(blockNode.spans, markDefs)}`);
    }
  } else {
    lines.push(`${prefix}${spansToMarkdown(blockNode.spans, markDefs)}`);
  }

  for (const child of blockNode.children || []) {
    lines.push(...irBlockToMarkdownLines(child, indent + 1));
  }

  if (blockNode.type === 'toggle') {
    lines.push(`${prefix}</details>`);
  }
  return lines;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export function markdownToIr(md) {
  const blocks = [];
  const lines = md.split('\n');
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const fenceMatch = /^(\s*)```([\w ]*?)$/.exec(line);
    if (fenceMatch) {
      const lang = fenceMatch[2].trim() || 'plain text';
      const codeLines = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        codeLines.push(lines[i]);
        i++;
      }
      appendBlock(blocks, (line.length - line.trimStart().length) >> 1, block('code', {
        text: codeLines.join('\n'),
        language: lang,
      }));
      i++;
      continue;
    }

    const stripped = line.trim();
    if (!stripped) {
      i++;
      continue;
    }

    appendBlock(blocks, (line.length - line.trimStart().length) >> 1, parseLineToIr(stripped));
    i++;
  }

  return blocks;
}

export function irToNotionBlocks(blocks) {
  return blocks.map(irBlockToNotion);
}

export function notionBlocksToIr(blocksMap, rootId) {
  const root = blocksMap[rootId]?.value ?? {};
  return (root.content || [])
    .map(id => blocksMap[id]?.value)
    .filter(blockNode => blockNode && blockNode.alive !== false)
    .map(blockNode => notionBlockToIr(blockNode, blocksMap));
}

export function irToMarkdown(blocks, indent = 0) {
  return blocks.flatMap(blockNode => irBlockToMarkdownLines(blockNode, indent)).join('\n');
}

export function markdownToBlocks(md) {
  return irToNotionBlocks(markdownToIr(md));
}

export function blocksToMarkdown(blocksMap, rootId, indent = 0) {
  return irToMarkdown(notionBlocksToIr(blocksMap, rootId), indent);
}
