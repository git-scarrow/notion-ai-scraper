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
import sys
import argparse
from typing import Any

try:
    from . import notion_api, config
except ImportError:
    import notion_api, config

# Use config instance
CFG = config.get_config()

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

def perform_return(client: notion_api.NotionAPIClient, page_id: str, summary: str = ""):
    """Update Work Item status and signal the Intake Clerk."""
    now = notion_api.now_iso()
    target_status = "Awaiting Intake"

    # Return paths should only signal Intake Clerk. Intake Clerk owns
    # Librarian Request Received At once it has actually ingested the result.
    properties = {
        "Status": {"status": {"name": target_status}},
        "Outcome": {"rich_text": [{"text": {"content": summary}}]} if summary else {},
        "Run Date": {"date": {"start": now}},
        "Return Received At": {"date": {"start": now}},
        "Return Consumed At": {"date": {"start": now}},
    }

    print(f"Updating Work Item {page_id} to '{target_status}'. Awaiting Intake Clerk.")
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
    
    if summary:
        client.append_block_children(page_id, [
            notion_api.heading_block("heading_3", "GitHub Return Summary"),
            notion_api.paragraph_block(summary)
        ])

    # TLA+ Lab-Loop-v1: Log state transition to Audit Log
    try:
        client.create_page(
            parent={"database_id": CFG.audit_log_db_id},
            properties={
                "Transition": {"title": [{"text": {"content": f"InProgress→{target_status}"}}]},
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

    perform_return(client, work_item["id"], args.summary)
    print(f"Successfully closed the loop for Work Item: {work_item.get('properties', {}).get('Item Name', {}).get('title', [{}])[0].get('plain_text', 'Unknown')}")

if __name__ == "__main__":
    main()
