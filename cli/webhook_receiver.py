#!/usr/bin/env python3
"""
webhook_receiver.py — FastAPI receiver for GitHub and Notion webhooks.

Routes:
  POST /github-return    — GitHub issues/PR closed → update Notion Work Item
  POST /notion-dispatch  — Notion public API webhook → dispatch to OpenClaw via run-lab-dispatch.sh

Installation:
  pip install fastapi uvicorn

Usage:
  uvicorn cli.webhook_receiver:app --host 0.0.0.0 --port 8000

Environment variables:
  GITHUB_WEBHOOK_SECRET   — GitHub webhook HMAC secret
  NOTION_WEBHOOK_SECRET   — Notion webhook verification_token (from subscription setup)
  NOTION_TOKEN            — Notion integration token (for dispatch.py)
  OPENCLAW_SSH_HOST       — SSH host for OpenClaw (default: nix)
  OPENCLAW_DISPATCH_CMD   — Command to run on the SSH host (default: see below)
"""

import os
import hmac
import hashlib
import json
import subprocess
import uuid
import logging
from fastapi import FastAPI, Request, HTTPException, Header
try:
    from . import github_return, notion_api, dispatch
except ImportError:
    import github_return, notion_api, dispatch

logger = logging.getLogger(__name__)

app = FastAPI()

# ── Secrets ──────────────────────────────────────────────────────────────────

GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET")
NOTION_WEBHOOK_SECRET = os.environ.get("NOTION_WEBHOOK_SECRET")
OPENCLAW_SSH_HOST = os.environ.get("OPENCLAW_SSH_HOST", "nix")
OPENCLAW_DISPATCH_CMD = os.environ.get(
    "OPENCLAW_DISPATCH_CMD",
    "sudo docker exec -i openclaw /home/node/nix-docker-configs/openclaw/run-lab-dispatch.sh --inside",
)


def _verify_hmac(payload: bytes, signature: str | None, secret: str | None) -> bool:
    """Verify sha256=<hex> HMAC signature. Passes if secret not configured."""
    if not secret:
        return True
    if not signature:
        return False
    mac = hmac.new(secret.encode(), msg=payload, digestmod=hashlib.sha256)
    expected = "sha256=" + mac.hexdigest()
    return hmac.compare_digest(expected, signature)


# ── Legacy alias kept for backward compatibility ──────────────────────────────

def verify_signature(payload: bytes, signature: str):
    """Verify that the webhook comes from GitHub."""
    return _verify_hmac(payload, signature, GITHUB_WEBHOOK_SECRET)

@app.post("/github-return")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(None),
    x_hub_signature_256: str = Header(None)
):
    payload_bytes = await request.body()
    
    if not verify_signature(payload_bytes, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = json.loads(payload_bytes)
    
    # Handle Issue Closed
    if x_github_event == "issues" and payload.get("action") == "closed":
        issue = payload["issue"]
        url = issue["html_url"]
        summary = f"Issue #{issue['number']} closed by {payload['sender']['login']}."
        return _handle_issue_closed(url, summary)

    # Handle PR Merged (closed with merged=true)
    if x_github_event == "pull_request" and payload.get("action") == "closed":
        pr = payload["pull_request"]
        if pr.get("merged"):
            url = pr["html_url"]
            summary = f"PR #{pr['number']} merged by {payload['sender']['login']}."
            return process_return(url, summary)

    # Handle issue comment → Prompt Notes (convention: ## Dispatch Prompt)
    if x_github_event == "issue_comment" and payload.get("action") == "created":
        comment = payload.get("comment", {})
        body = comment.get("body", "")
        if body.lstrip().startswith("## Dispatch Prompt"):
            issue = payload["issue"]
            url = issue["html_url"]
            return _handle_prompt_comment(url, body)

    return {"status": "ignored", "reason": "event_not_handled"}

def _handle_issue_closed(url: str, summary: str):
    """Issue-closed path with dedup guard.

    If the PR merge handler already ran first it will have set Status to
    'Awaiting Intake' while preserving GitHub Issue URL. In that case the Work
    Item won't be found (URL cleared) OR it will be found but already in
    the target state — either way skip to avoid a double audit-log entry
    and a redundant Notion write.
    """
    try:
        token = os.environ.get("NOTION_TOKEN")
        if not token:
            raise RuntimeError("NOTION_TOKEN environment variable required")
        client = notion_api.NotionAPIClient(token)

        work_item = github_return.find_work_item_by_url(client, url)
        if not work_item:
            return {"status": "error", "reason": "work_item_not_found", "url": url}

        current_status = (
            work_item.get("properties", {})
            .get("Status", {})
            .get("status", {})
            .get("name")
        )
        if current_status == "Awaiting Intake":
            logger.info("Skipping issue_closed for %s — already Awaiting Intake (PR merge handled it)", url)
            return {"status": "skipped", "reason": "already_awaiting_intake", "work_item_id": work_item["id"]}

        github_return.perform_return(client, work_item["id"], summary)
        return {"status": "success", "work_item_id": work_item["id"]}
    except Exception as e:
        logger.error("Error in _handle_issue_closed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


PROMPT_MARKER = "## Dispatch Prompt"


def _handle_prompt_comment(issue_url: str, comment_body: str):
    """Copy a '## Dispatch Prompt' comment into the Work Item's Prompt Notes.

    Latest matching comment wins — each delivery overwrites the previous value.
    Only comments whose body starts with '## Dispatch Prompt' are picked up;
    regular discussion comments are ignored.
    """
    try:
        token = os.environ.get("NOTION_TOKEN")
        if not token:
            raise RuntimeError("NOTION_TOKEN environment variable required")
        client = notion_api.NotionAPIClient(token)

        work_item = github_return.find_work_item_by_url(client, issue_url)
        if not work_item:
            return {"status": "error", "reason": "work_item_not_found", "url": issue_url}

        # Notion rich_text has a 2000-char limit per segment
        prompt_text = comment_body
        segments = []
        while prompt_text:
            segments.append({"type": "text", "text": {"content": prompt_text[:2000]}})
            prompt_text = prompt_text[2000:]

        client.update_page(work_item["id"], properties={
            "Prompt Notes": {"rich_text": segments},
        })

        logger.info("Wrote Prompt Notes for %s from issue %s", work_item["id"], issue_url)
        return {"status": "prompt_written", "work_item_id": work_item["id"]}
    except Exception as e:
        logger.error("Error in _handle_prompt_comment: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


def process_return(url: str, summary: str):
    """Bridge to the return logic."""
    try:
        token = os.environ.get("NOTION_TOKEN")
        if not token:
            raise RuntimeError("NOTION_TOKEN environment variable required")
        client = notion_api.NotionAPIClient(token)
        
        work_item = github_return.find_work_item_by_url(client, url)
        if not work_item:
            return {"status": "error", "reason": "work_item_not_found", "url": url}
        
        github_return.perform_return(client, work_item["id"], summary)
        return {"status": "success", "work_item_id": work_item["id"]}
    except Exception as e:
        print(f"Error processing return: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ── Notion dispatch webhook ──────────────────────────────────────────────────


def _dispatch_to_openclaw(packet: dict) -> str:
    """Pipe a dispatch packet to run-lab-dispatch.sh via SSH.

    Returns a status string. Runs asynchronously (fire-and-forget) so the
    webhook response isn't blocked by the full execution.
    """
    packet_json = json.dumps(packet)
    cmd = f"ssh {OPENCLAW_SSH_HOST} {OPENCLAW_DISPATCH_CMD}"
    try:
        proc = subprocess.Popen(
            cmd, shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        proc.stdin.write(packet_json.encode())
        proc.stdin.close()
        # Don't wait — execution can take 10+ minutes
        logger.info("Spawned run-lab-dispatch.sh (pid=%s) for %s", proc.pid, packet.get("work_item_name"))
        return f"spawned (pid={proc.pid})"
    except Exception as e:
        logger.error("Failed to spawn run-lab-dispatch.sh: %s", e)
        return f"error: {e}"


@app.post("/notion-dispatch")
async def notion_dispatch_webhook(
    request: Request,
    x_notion_signature: str = Header(None),
):
    """Receive Notion public API webhook events for the Work Items database.

    Handles two flows:
    1. Subscription verification: Notion POSTs {"verification_token": "..."}
       during setup. Log the token — paste it into the Notion UI to activate.
    2. page.properties_updated events: build dispatch packet, stamp consumed,
       pipe to run-lab-dispatch.sh on OpenClaw.

    Returns 200 on validation failures so Notion does not retry bad items.
    """
    payload_bytes = await request.body()

    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # ── Step 1: Subscription verification ────────────────────────────────
    if "verification_token" in payload and "type" not in payload:
        token = payload["verification_token"]
        logger.info("Notion webhook verification token received: %s", token)
        # Print to stdout so it's visible in service logs
        print(f"\n{'='*60}")
        print(f"NOTION WEBHOOK VERIFICATION TOKEN: {token}")
        print(f"Paste this into the Notion integration Webhooks tab.")
        print(f"{'='*60}\n")
        return {"status": "verification_received"}

    # ── Step 2: Verify signature on real events ──────────────────────────
    if not _verify_hmac(payload_bytes, x_notion_signature, NOTION_WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid Notion signature")

    # ── Step 3: Filter event type ────────────────────────────────────────
    event_type = payload.get("type", "")
    if event_type != "page.properties_updated":
        return {"status": "ignored", "reason": f"event_type={event_type}"}

    # ── Step 4: Extract page ID ──────────────────────────────────────────
    raw_id = (payload.get("entity") or {}).get("id")
    if not raw_id:
        return {"status": "ignored", "reason": "no_entity_id"}

    try:
        page_id = str(uuid.UUID(str(raw_id).replace("-", "")))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid entity id: {raw_id!r}")

    # ── Step 5: Build and validate dispatch packet ───────────────────────
    try:
        result = dispatch.build_dispatch_packet(page_id)
    except Exception as e:
        logger.error("build_dispatch_packet(%s) failed: %s", page_id, e)
        # Return 200 — this page may not be a dispatchable Work Item
        return {"status": "not_dispatchable", "page_id": page_id, "error": str(e)}

    if result["errors"]:
        logger.info("Dispatch validation failed for %s: %s", page_id, result["errors"])
        return {"status": "validation_failed", "page_id": page_id, "errors": result["errors"]}

    packet = result["packet"]
    run_id = packet["run_id"]

    # ── Step 6: Stamp consumed (with race guard) ─────────────────────────
    try:
        stamp_result = dispatch.stamp_dispatch_consumed(page_id, run_id)
    except Exception as e:
        logger.error("stamp_dispatch_consumed(%s, %s) failed: %s", page_id, run_id, e)
        return {"status": "stamp_failed", "page_id": page_id, "error": str(e)}

    if stamp_result.get("status") in ("already_consumed", "wrong_status"):
        logger.info("Skipping %s: %s", page_id, stamp_result)
        return {"status": "skipped", "page_id": page_id, "reason": stamp_result}

    # ── Step 7: Dispatch to OpenClaw ─────────────────────────────────────
    openclaw_result = _dispatch_to_openclaw(packet)

    logger.info(
        "Dispatched %s (run_id=%s, lane=%s, openclaw=%s)",
        page_id, run_id, packet.get("execution_lane"), openclaw_result,
    )
    return {
        "status": "dispatched",
        "page_id": page_id,
        "run_id": run_id,
        "lane": packet.get("execution_lane"),
        "work_item_name": packet.get("work_item_name"),
        "openclaw": openclaw_result,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
