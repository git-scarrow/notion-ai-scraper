// block-builder.js — Markdown ↔ Notion block conversion.
// JS port of cli/block_builder.py.
// Used in the extension page to parse markdown before injection.


function richText(text) {
  const segments = [];
  // First split on mention tokens, then parse formatting in each chunk
  const parts = text.split(/(\{\{\w+:[0-9a-f-]+\}\})/g);
  for (const part of parts) {
    if (!part) continue;
    const mentionMatch = /^\{\{(\w+):([0-9a-f-]+)\}\}$/.exec(part);
    if (mentionMatch) {
      const ann = MENTION_CODES[mentionMatch[1]] || mentionMatch[1];
      segments.push(['\u2023', [[ann, mentionMatch[2]]]]);
      continue;
    }
    // Parse formatting within this non-mention chunk
    const fmtPattern = /\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`|([^*`]+)/g;
    let m;
    while ((m = fmtPattern.exec(part)) !== null) {
      const [, bold, italic, inlineCode, plain] = m;
      if (bold)            segments.push([bold,       [['b']]]);
      else if (italic)     segments.push([italic,     [['i']]]);
      else if (inlineCode) segments.push([inlineCode, [['c']]]);
      else if (plain)      segments.push([plain]);
    }
  }
  return segments.length ? segments : [[text]];
}


function parseLine(s) {
  let m2;
  if ((m2 = /^### (.+)/.exec(s))) {
    return { type: 'sub_sub_header', properties: { title: richText(m2[1]) } };
  } else if ((m2 = /^## (.+)/.exec(s))) {
    return { type: 'sub_header', properties: { title: richText(m2[1]) } };
  } else if ((m2 = /^# (.+)/.exec(s))) {
    return { type: 'header', properties: { title: richText(m2[1]) } };
  } else if (/^[-*_]{3,}$/.test(s)) {
    return { type: 'divider', properties: {} };
  } else if (s.startsWith('>')) {
    const text = s.replace(/^>\s*/, '');
    const em = /^(\p{Emoji_Presentation}|\p{Extended_Pictographic})\s*(.*)/u.exec(text);
    if (em) {
      return { type: 'callout', properties: { title: richText(em[2]) }, format: { page_icon: em[1] } };
    } else {
      return { type: 'callout', properties: { title: richText(text) }, format: { page_icon: '📌' } };
    }
  } else if (/^[-*+] /.test(s)) {
    return { type: 'bulleted_list', properties: { title: richText(s.replace(/^[-*+] /, '')) } };
  } else if (/^\d+\. /.test(s)) {
    return { type: 'numbered_list', properties: { title: richText(s.replace(/^\d+\. /, '')) } };
  } else {
    return { type: 'text', properties: { title: richText(s) } };
  }
}

export function markdownToBlocks(md) {
  const blocks = [];
  const lines = md.split('\n');
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Fenced code block (no nesting)
    const fenceMatch = /^(\s*)```(\w*)$/.exec(line);
    if (fenceMatch) {
      const lang = fenceMatch[2] || 'plain text';
      const codeLines = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        codeLines.push(lines[i]);
        i++;
      }
      blocks.push({
        type: 'code',
        properties: { title: [[codeLines.join('\n')]], language: [[lang]] },
      });
      i++;
      continue;
    }

    const s = line.trim();
    if (!s) { i++; continue; }

    // Measure indent level (2 spaces per level)
    const indent = (line.length - line.trimStart().length) >> 1;
    const block = parseLine(s);

    if (indent > 0 && blocks.length > 0) {
      // Find the ancestor at (indent - 1) depth
      let parent = blocks[blocks.length - 1];
      for (let d = 1; d < indent; d++) {
        if (parent.children?.length) parent = parent.children[parent.children.length - 1];
        else break;
      }
      if (!parent.children) parent.children = [];
      parent.children.push(block);
    } else {
      blocks.push(block);
    }

    i++;
  }

  return blocks;
}


// Mention type codes used by Notion rich text annotations
const MENTION_TYPES = { p: 'page', u: 'user', d: 'date', a: 'agent', s: 'space' };
const MENTION_CODES = Object.fromEntries(Object.entries(MENTION_TYPES).map(([k, v]) => [v, k]));

function richTextToMarkdown(segments) {
  return segments.map(seg => {
    const text = seg[0] ?? '';
    const ann = seg[1];
    if (!ann || !Array.isArray(ann)) return text;

    // Check for mention pointer (‣ with a type+uuid annotation)
    if (text === '\u2023') {
      for (const a of ann) {
        if (Array.isArray(a) && a.length >= 2) {
          const type = MENTION_TYPES[a[0]] || a[0];
          return `{{${type}:${a[1]}}}`;
        }
      }
      return text; // fallback — bare ‣
    }

    let out = text;
    for (const a of ann) {
      if (!Array.isArray(a)) continue;
      if (a[0] === 'b') out = `**${out}**`;
      else if (a[0] === 'i') out = `*${out}*`;
      else if (a[0] === 'c') out = `\`${out}\``;
    }
    return out;
  }).join('');
}

export function blocksToMarkdown(blocksMap, rootId, indent = 0) {
  const lines = [];
  const root = blocksMap[rootId]?.value ?? {};
  const children = root.content ?? [];
  const prefix = '  '.repeat(indent);

  for (const cid of children) {
    const block = blocksMap[cid]?.value;
    if (!block) continue;

    const { type, properties = {}, format = {}, content: subContent } = block;
    const titleRt = properties.title ?? [];
    const text = richTextToMarkdown(titleRt);

    if      (type === 'header')          lines.push(`${prefix}# ${text}`);
    else if (type === 'sub_header')      lines.push(`${prefix}## ${text}`);
    else if (type === 'sub_sub_header')  lines.push(`${prefix}### ${text}`);
    else if (type === 'bulleted_list')   lines.push(`${prefix}- ${text}`);
    else if (type === 'numbered_list')   lines.push(`${prefix}1. ${text}`);
    else if (type === 'divider')         lines.push(`${prefix}---`);
    else if (type === 'callout') {
      const icon = format.page_icon ?? '';
      lines.push(`${prefix}> ${icon} ${text}`.trimEnd());
    } else if (type === 'code') {
      const lang = (properties.language ?? [['']])[0]?.[0] ?? '';
      lines.push(`${prefix}\`\`\`${lang}`, text, `${prefix}\`\`\``);
    } else {
      lines.push(`${prefix}${text}`);
    }

    if (subContent?.length) {
      lines.push(blocksToMarkdown(blocksMap, cid, indent + 1));
    }
  }

  return lines.join('\n');
}
