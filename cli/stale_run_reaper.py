#!/usr/bin/env python3
"""Stale-run reaper: resets orphaned In Progress work items for re-dispatch.

Runs outside OpenClaw (systemd timer, cron, or manual) so it survives
gateway restarts. Uses the Notion public API only.

An item is considered stale when:
  - Status = In Progress
  - Dispatch Requested Consumed At is older than STALE_THRESHOLD_HOURS
  - Return Received At is empty (no completion signal)

Reset action:
  - Status → Not Started
  - Clear Dispatch Requested Consumed At
  - Clear run_id
  - Log to Lab Audit Log
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta

# Allow running from repo root or cli/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import Config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger("stale-run-reaper")

# ---------------------------------------------------------------------------
# Notion API helpers
# ---------------------------------------------------------------------------

import requests

API = "https://api.notion.com/v1"


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }


def _notion_post(token: str, endpoint: str, body: dict) -> dict:
    resp = requests.post(f"{API}/{endpoint}", headers=_headers(token), json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _notion_patch(token: str, endpoint: str, body: dict) -> dict:
    resp = requests.patch(f"{API}/{endpoint}", headers=_headers(token), json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Query for stale items
# ---------------------------------------------------------------------------


def find_stale_items(token: str, db_id: str, threshold: timedelta) -> list[dict]:
    """Find In Progress items with stale dispatch consumption and no return."""
    cutoff = (datetime.now(timezone.utc) - threshold).isoformat()

    filter_obj = {
        "and": [
            {"property": "Status", "status": {"equals": "In Progress"}},
            {
                "property": "Dispatch Requested Consumed At",
                "date": {"before": cutoff},
            },
            {
                "property": "Return Received At",
                "date": {"is_empty": True},
            },
        ]
    }

    results = []
    cursor = None
    while True:
        body: dict = {
            "filter": filter_obj,
            "page_size": 100,
        }
        if cursor:
            body["start_cursor"] = cursor

        data = _notion_post(token, f"databases/{db_id}/query", body)
        for page in data.get("results", []):
            props = page.get("properties", {})
            title_prop = props.get("Item Name", {})
            title_parts = title_prop.get("title", [])
            name = title_parts[0]["plain_text"] if title_parts else "(untitled)"

            consumed_prop = props.get("Dispatch Requested Consumed At", {})
            consumed_date = consumed_prop.get("date", {})
            consumed_at = consumed_date.get("start") if consumed_date else None

            run_id_prop = props.get("run_id", {})
            run_id_parts = run_id_prop.get("rich_text", [])
            run_id = run_id_parts[0]["plain_text"] if run_id_parts else ""

            results.append({
                "id": page["id"],
                "name": name,
                "consumed_at": consumed_at,
                "run_id": run_id,
                "url": page["url"],
            })

        if data.get("has_more") and data.get("next_cursor"):
            cursor = data["next_cursor"]
        else:
            break

    return results


# ---------------------------------------------------------------------------
# Reset a stale item
# ---------------------------------------------------------------------------


def reset_item(token: str, page_id: str) -> None:
    """Reset a stale work item for re-dispatch."""
    _notion_patch(token, f"pages/{page_id}", {
        "properties": {
            "Status": {"status": {"name": "Not Started"}},
            "Dispatch Requested Consumed At": {"date": None},
            "run_id": {"rich_text": []},
        }
    })


def log_audit(token: str, audit_db_id: str, item_id: str, item_name: str) -> None:
    """Write an audit log entry for the reset."""
    _notion_post(token, "pages", {
        "parent": {"database_id": audit_db_id},
        "properties": {
            "Transition": {
                "title": [{"text": {"content": f"Stale-run reset: {item_name}"}}]
            },
            "Agent": {"select": {"name": "Dispatch Adapter"}},
            "From Status": {"select": {"name": "In Progress"}},
            "To Status": {"select": {"name": "Not Started"}},
            "Work Item": {"relation": [{"id": item_id}]},
            "Consumption Timestamp": {
                "date": {"start": datetime.now(timezone.utc).isoformat()}
            },
        },
    })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Reset stale In Progress work items")
    parser.add_argument(
        "--threshold-hours",
        type=float,
        default=4.0,
        help="Hours since dispatch consumption before item is considered stale (default: 4)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List stale items without resetting them",
    )
    args = parser.parse_args()

    try:
        cfg = Config.from_env()
    except ValueError as e:
        log.error(str(e))
        sys.exit(1)

    if not cfg.work_items_db_id:
        log.error("WORK_ITEMS_DB_ID not configured")
        sys.exit(1)

    threshold = timedelta(hours=args.threshold_hours)
    log.info("Scanning for items stale > %s hours", args.threshold_hours)

    stale = find_stale_items(cfg.notion_token, cfg.work_items_db_id, threshold)

    if not stale:
        log.info("No stale items found")
        return

    for item in stale:
        age_str = item["consumed_at"] or "unknown"
        if args.dry_run:
            log.info("[DRY RUN] Would reset: %s (consumed %s, run_id=%s)", item["name"], age_str, item["run_id"])
        else:
            log.info("Resetting: %s (consumed %s, run_id=%s)", item["name"], age_str, item["run_id"])
            try:
                reset_item(cfg.notion_token, item["id"])
                if cfg.audit_log_db_id:
                    log_audit(cfg.notion_token, cfg.audit_log_db_id, item["id"], item["name"])
                log.info("  → Reset complete, audit logged")
            except Exception as e:
                log.error("  → Failed to reset %s: %s", item["name"], e)

    log.info("Done: %d item(s) %s", len(stale), "would be reset" if args.dry_run else "reset")


if __name__ == "__main__":
    main()
