#!/usr/bin/env python3
"""
dashboard_server.py — Notion-powered BI dashboard HTTP server.

Exposes chart-ready JSON from Notion databases and serves the dashboard UI.
Connector pattern inspired by Redash's BaseQueryRunner (BSD-2-Clause).

Usage:
    cli/.venv/bin/python cli/dashboard_server.py [--port 8099]
    # Then open http://localhost:8099
"""
import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import notion_api

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, FileResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
import uvicorn

CFG = config.get_config()

DASHBOARD_DIR = Path(__file__).parent.parent / "dashboard"

# Known databases — sourced from config (template-data.json / env overrides)
_KNOWN_DBS: dict[str, tuple[str, str]] = {
    "work_items":   ("Work Items",   CFG.work_items_db_id),
    "lab_projects": ("Lab Projects", CFG.lab_projects_db_id),
    "audit_log":    ("Audit Log",    CFG.audit_log_db_id),
}


def _client() -> notion_api.NotionAPIClient:
    return notion_api.NotionAPIClient(token=CFG.notion_token)


# ── Property extraction ────────────────────────────────────────────────────────

def _extract_value(prop: dict):
    """Flatten a Notion property to a JSON-serializable primitive."""
    t = prop.get("type", "")
    if t == "title":
        return "".join(x.get("plain_text", "") for x in prop.get("title", []))
    if t == "rich_text":
        return "".join(x.get("plain_text", "") for x in prop.get("rich_text", []))
    if t in ("select", "status"):
        v = prop.get(t)
        return v["name"] if isinstance(v, dict) else None
    if t == "multi_select":
        return [o["name"] for o in prop.get("multi_select", [])]
    if t == "number":
        return prop.get("number")
    if t == "checkbox":
        return bool(prop.get("checkbox"))
    if t == "date":
        d = prop.get("date")
        return d.get("start") if isinstance(d, dict) else None
    if t in ("created_time", "last_edited_time"):
        return prop.get(t)
    if t in ("created_by", "last_edited_by"):
        p = prop.get(t, {})
        return p.get("name", p.get("id")) if isinstance(p, dict) else None
    if t == "url":
        return prop.get("url")
    if t == "unique_id":
        uid = prop.get("unique_id", {})
        pre = uid.get("prefix", "")
        n = uid.get("number", "")
        return f"{pre}-{n}" if pre else str(n)
    return None


def _to_rows(pages: list, schema: dict) -> list[dict]:
    """Convert raw Notion pages to flat dicts for chart consumption."""
    rows = []
    for page in pages:
        row: dict = {"_id": page.get("id"), "_url": page.get("url")}
        for name, prop in page.get("properties", {}).items():
            row[name] = _extract_value(prop)
        rows.append(row)
    return rows


def _get_schema(client: notion_api.NotionAPIClient, db_id: str) -> dict[str, str]:
    """Return {prop_name: prop_type} from Notion database metadata."""
    db = client.retrieve_database(db_id)
    props = db.get("properties", {})
    return {name: info.get("type", "") for name, info in props.items()}


def _aggregate(pages: list, schema: dict) -> dict:
    """Compute per-column statistics as a JSON-serializable dict.

    Returns frequencies for categorical columns, range/mean for numeric,
    and date bounds for temporal columns.
    """
    stats: dict[str, dict] = {}
    for name, ptype in schema.items():
        vals = [_extract_value(page.get("properties", {}).get(name, {})) for page in pages]
        if ptype in ("select", "status"):
            counter: Counter = Counter(v or "(empty)" for v in vals)
            stats[name] = {"type": ptype, "distribution": dict(counter.most_common())}
        elif ptype == "multi_select":
            tag_counter: Counter = Counter()
            for v in vals:
                for tag in (v or []):
                    tag_counter[tag] += 1
            stats[name] = {"type": ptype, "distribution": dict(tag_counter.most_common(20))}
        elif ptype == "number":
            nums = [v for v in vals if v is not None]
            if nums:
                stats[name] = {
                    "type": ptype,
                    "count": len(nums),
                    "min": min(nums),
                    "max": max(nums),
                    "mean": round(sum(nums) / len(nums), 4),
                }
        elif ptype == "checkbox":
            true_count = sum(1 for v in vals if v)
            stats[name] = {"type": ptype, "true": true_count, "false": len(vals) - true_count}
        elif ptype in ("date", "created_time", "last_edited_time"):
            dates = sorted(v[:10] for v in vals if v)  # YYYY-MM-DD
            if dates:
                stats[name] = {"type": ptype, "count": len(dates),
                               "earliest": dates[0], "latest": dates[-1],
                               "by_date": dict(Counter(dates))}
    return {"total": len(pages), "columns": stats}


# ── Route handlers ─────────────────────────────────────────────────────────────

async def api_databases(request: Request) -> JSONResponse:
    return JSONResponse({
        "databases": [
            {"id": db_id, "label": label, "key": key}
            for key, (label, db_id) in _KNOWN_DBS.items()
            if db_id
        ]
    })


async def api_schema(request: Request) -> JSONResponse:
    db_id = request.path_params["db_id"]
    try:
        schema = _get_schema(_client(), db_id)
        return JSONResponse({"schema": schema})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_query(request: Request) -> JSONResponse:
    db_id = request.path_params["db_id"]
    params = request.query_params
    limit = min(int(params.get("limit", 100)), 200)
    filter_param = params.get("filter")
    sorts_param = params.get("sorts")
    try:
        client = _client()
        schema = _get_schema(client, db_id)
        filter_obj = json.loads(filter_param) if filter_param else None
        sorts_obj = json.loads(sorts_param) if sorts_param else None
        pages: list = []
        cursor = None
        while len(pages) < limit:
            batch_size = min(100, limit - len(pages))
            result = client.query_database(
                db_id,
                filter_payload=filter_obj,
                start_cursor=cursor,
                page_size=batch_size,
            )
            pages.extend(result.get("results", []))
            if not result.get("has_more"):
                break
            cursor = result.get("next_cursor")
        rows = _to_rows(pages, schema)
        return JSONResponse({"schema": schema, "rows": rows, "total": len(rows)})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_aggregate(request: Request) -> JSONResponse:
    db_id = request.path_params["db_id"]
    try:
        client = _client()
        schema = _get_schema(client, db_id)
        pages = client.query_all(db_id)
        return JSONResponse(_aggregate(pages, schema))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def index(request: Request) -> FileResponse:
    return FileResponse(DASHBOARD_DIR / "index.html")


# ── App ────────────────────────────────────────────────────────────────────────

routes = [
    Route("/", index),
    Route("/api/databases", api_databases),
    Route("/api/schema/{db_id:str}", api_schema),
    Route("/api/query/{db_id:str}", api_query),
    Route("/api/aggregate/{db_id:str}", api_aggregate),
    Mount("/static", StaticFiles(directory=str(DASHBOARD_DIR))),
]

app = Starlette(routes=routes)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Notion Forge dashboard server")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    print(f"Dashboard → http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
