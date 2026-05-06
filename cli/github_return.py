#!/usr/bin/env python3
"""
github_return.py — Deterministic handoff from GitHub back to the Lab.

Triggered by GitHub Actions (issue.closed or pull_request.closed).
1. Finds the Work Item in Notion where 'GitHub Issue URL' matches.
2. Moves the Work Item into the return phase.
3. Writes return timestamps for Intake Clerk to consume.
4. Records the Run Date and audit trail.
"""

import os
import re
import sys
import json
import argparse
import subprocess
from typing import Any

try:
    from . import notion_api, config
except ImportError:
    import notion_api, config

# Use config instance
CFG = config.get_config()

_GITHUB_ISSUE_RE = re.compile(
    r"https://github\.com/([^/]+)/([^/]+)/issues/(\d+)"
)


def parse_github_issue_url(url: str) -> tuple[str, str, int] | None:
    """Return (owner, repo, number) from a GitHub issue URL, or None."""
    m = _GITHUB_ISSUE_RE.match(url.split("?")[0].rstrip("/"))
    if not m:
        return None
    return m.group(1), m.group(2), int(m.group(3))


def fetch_issue_comments(owner: str, repo: str, issue_number: int) -> list[dict]:
    """Fetch all comments for a GitHub issue via gh CLI.

    Returns a list of comment dicts with keys: id, user, body, created_at.
    Returns [] on any failure so callers can degrade gracefully.
    """
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{owner}/{repo}/issues/{issue_number}/comments",
             "--paginate", "--jq", ".[] | {id: .id, user: .user.login, body: .body, created_at: .created_at}"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            print(f"WARNING: gh api comments failed (rc={result.returncode}): {result.stderr.strip()}")
            return []
        # --jq outputs one JSON object per line (NDJSON)
        comments = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line:
                comments.append(json.loads(line))
        return comments
    except Exception as e:
        print(f"WARNING: fetch_issue_comments failed: {e}")
        return []


def find_work_item_by_url(client: notion_api.NotionAPIClient, url: str) -> dict[str, Any] | None:
    """Find a Work Item page where 'GitHub Issue URL' matches."""
    print(f"Searching for Work Item with GitHub Issue URL: {url}")
    # Note: 'GitHub Issue URL' internal ID is '_?XB' from previous schema reads
    filter_payload = {
        "property": "GitHub Issue URL",
        "url": {"equals": url}
    }
    results = client.query_all(CFG.work_items_db_id, filter_payload=filter_payload, page_size=1)
    return results[0] if results else None

def perform_return(
    client: notion_api.NotionAPIClient,
    page_id: str,
    summary: str = "",
    comments: list[dict] | None = None,
) -> str:
    """Update Work Item status and signal the Intake Clerk.

    Args:
        comments: GitHub issue comment dicts from fetch_issue_comments().
                  When provided and non-empty, bodies are written to the Work
                  Item page before Intake Clerk fires (AC-1). The audit log
                  entry is tagged [evidence:full] vs [evidence:close_state_only]
                  (AC-3).

    Returns:
        The evidence quality string: "full" or "close_state_only".
    """
    now = notion_api.now_iso()
    target_status = "Awaiting Intake"
    has_comments = bool(comments)
    evidence_tag = "full" if has_comments else "close_state_only"

    # Return paths should only signal Intake Clerk. Intake Clerk owns
    # Librarian Request Received At once it has actually ingested the result.
    properties = {
        "Status": {"status": {"name": target_status}},
        "Run Date": {"date": {"start": now}},
        "Return Received At": {"date": {"start": now}},
        "Return Consumed At": {"date": {"start": now}},
    }
    if summary:
        properties["Outcome"] = {"rich_text": [{"text": {"content": summary}}]}

    print(f"Updating Work Item {page_id} to '{target_status}'. evidence={evidence_tag}. Awaiting Intake Clerk.")
    try:
        client.update_page(page_id, properties=properties)
    except Exception as e:
        if target_status in str(e):
            print("Fallback: 'Awaiting Intake' status missing. Using legacy 'Done'.")
            target_status = "Done"
            properties["Status"] = {"status": {"name": target_status}}
            client.update_page(page_id, properties=properties)
        else:
            raise e

    # Build blocks: close summary + comment bodies (AC-1)
    blocks: list[dict] = []
    if summary:
        blocks += [
            notion_api.heading_block("heading_3", "GitHub Return Summary"),
            notion_api.paragraph_block(summary),
        ]
    if has_comments:
        blocks.append(notion_api.heading_block("heading_3", "GitHub Issue Comments"))
        for c in comments:
            author = c.get("user", "unknown")
            created = c.get("created_at", "")[:10]
            header = f"{author} — {created}" if created else author
            blocks += [
                notion_api.heading_block("heading_4", header),
                notion_api.paragraph_block(c.get("body", "")),
            ]

    if blocks:
        client.append_block_children(page_id, blocks)

    # TLA+ Lab-Loop-v1: Log state transition to Audit Log (AC-3: evidence tag in Transition)
    try:
        transition_label = f"InProgress→{target_status} [evidence:{evidence_tag}]"
        client.create_page(
            parent={"database_id": CFG.audit_log_db_id},
            properties={
                "Transition": {"title": [{"text": {"content": transition_label}}]},
                "Work Item": {"relation": [{"id": page_id}]},
                "Agent": {"select": {"name": "Webhook Bridge"}},
                "From Status": {"select": {"name": "In Progress"}},
                "To Status": {"select": {"name": target_status}},
                "Signal Consumed": {"select": {"name": "LR"}},
                "Consumption Timestamp": {"date": {"start": now}},
            },
        )
    except Exception as e:
        print(f"WARNING: Audit log write failed (non-fatal): {e}")

    return evidence_tag

def main():
    parser = argparse.ArgumentParser(description="Lab Return Hook")
    parser.add_argument("--url", required=True, help="GitHub Issue or PR URL")
    parser.add_argument("--summary", help="Closing summary or description")
    args = parser.parse_args()

    token = CFG.notion_token
    client = notion_api.NotionAPIClient(token)


    work_item = find_work_item_by_url(client, args.url)

    if not work_item:
        print(f"ERROR: No Work Item found for URL: {args.url}")
        sys.exit(1)

    comments: list[dict] = []
    parsed = parse_github_issue_url(args.url)
    if parsed:
        owner, repo, number = parsed
        comments = fetch_issue_comments(owner, repo, number)
        print(f"Fetched {len(comments)} comment(s) from GitHub.")

    evidence = perform_return(client, work_item["id"], args.summary, comments=comments)
    item_name = work_item.get("properties", {}).get("Item Name", {}).get("title", [{}])[0].get("plain_text", "Unknown")
    print(f"Successfully closed the loop for Work Item: {item_name} [evidence:{evidence}]")

if __name__ == "__main__":
    main()
