#!/usr/bin/env python3
"""Fetch and clean published essays for the evaluation matrix.

Usage:
    python cli/eval/fetch_essays.py --essay unbelievable-story
    python cli/eval/fetch_essays.py --essay gilded-age
    python cli/eval/fetch_essays.py --all

Each fetched essay is saved as a self-contained input packet in cli/eval/essays/.
"""

import argparse
import os
import re
import sys

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
ESSAYS_DIR = os.path.join(EVAL_DIR, "essays")

SOURCES = {
    "unbelievable-story": {
        "url": "https://www.propublica.org/article/false-rape-accusations-an-unbelievable-story",
        "title": "An Unbelievable Story of Rape",
        "outlet": "ProPublica / The Marshall Project",
        "type": "Braid / dual-strand",
    },
    "gilded-age": {
        "url": "https://magazine.atavist.com/2021/the-gilded-age-peru-gold-ntr-elemetal-illegal-mining-ferrari",
        "title": "The Gilded Age",
        "outlet": "The Atavist Magazine",
        "type": "Detective / inquiry",
    },
}


def _clean_html(html: str) -> str:
    """Strip HTML to plain text, preserving paragraph breaks."""
    # Remove script/style blocks
    html = re.sub(r'<(script|style|nav|header|footer|aside)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # Convert block-level elements to newlines
    html = re.sub(r'<(?:p|div|br|h[1-6]|blockquote|li|tr)[^>]*/?>', '\n', html, flags=re.IGNORECASE)
    # Strip remaining tags
    html = re.sub(r'<[^>]+>', '', html)
    # Decode entities
    html = html.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    html = html.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
    html = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), html)
    # Collapse whitespace
    lines = []
    for line in html.split('\n'):
        stripped = line.strip()
        if stripped:
            lines.append(stripped)
        elif lines and lines[-1] != '':
            lines.append('')
    return '\n\n'.join(para for para in '\n'.join(lines).split('\n\n') if para.strip())


def _wrap_as_packet(title: str, outlet: str, essay_type: str, body: str) -> str:
    """Wrap cleaned article text in the standardized input packet format."""
    return f"""## Essay Review Request

### Core Idea Packet
- **Thesis**: [Inferred from the piece — this is a published work used as evaluation input]
- **Contribution**: [Inferred]
- **Non-Goals**: not provided
- **Red Lines**: not provided
- **Revision Notes**: "Published piece used as evaluation input — no revision history"

### Source
- **Title**: {title}
- **Outlet**: {outlet}
- **Structural type**: {essay_type}

### Draft

{body}
"""


def fetch_essay(key: str) -> str:
    """Fetch and clean a published essay. Returns the output file path."""
    if key not in SOURCES:
        raise ValueError(f"Unknown essay: {key}. Available: {', '.join(SOURCES)}")

    src = SOURCES[key]
    out_path = os.path.join(ESSAYS_DIR, f"{key}.md")

    # Attempt fetch via urllib (no external deps)
    import urllib.request
    import urllib.error

    print(f"Fetching {src['title']} from {src['url']}...", file=sys.stderr)
    req = urllib.request.Request(src["url"], headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:138.0) Gecko/20100101 Firefox/138.0",
        "Accept": "text/html",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        print(f"Fetch failed: {e}. Use Playwright MCP or manual download.", file=sys.stderr)
        return ""

    body = _clean_html(html)
    if len(body) < 1000:
        print(f"Warning: extracted body is only {len(body)} chars — may need Playwright.", file=sys.stderr)

    packet = _wrap_as_packet(src["title"], src["outlet"], src["type"], body)

    os.makedirs(ESSAYS_DIR, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(packet)

    print(f"Saved {out_path} ({len(body)} chars body)", file=sys.stderr)
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Fetch evaluation essays")
    parser.add_argument("--essay", choices=list(SOURCES.keys()), help="Fetch a specific essay")
    parser.add_argument("--all", action="store_true", help="Fetch all essays")
    args = parser.parse_args()

    if args.all:
        for key in SOURCES:
            fetch_essay(key)
    elif args.essay:
        fetch_essay(args.essay)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
