"""Durable transition log for Lab dispatch/return events.

Event-sourced local sqlite record alongside Notion's Audit Log database.
Notion remains the visible state plane; this provides deterministic
transition IDs and replay-safe event chains for offline analysis.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Literal

logger = logging.getLogger(__name__)

EventType = Literal[
    "dispatch.accepted",
    "return.received",
    "return.direct_closeout",
    "github.closeout",
    "intake.triggered",
]

DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "notion-forge" / "transitions.db"

_db_path: Path = DEFAULT_DB_PATH


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _make_transition_id(work_item_id: str, event_type: str, run_id: str | None, ts: datetime) -> str:
    raw = f"{work_item_id}|{event_type}|{run_id or ''}|{ts.isoformat()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class TransitionEvent:
    transition_id: str
    work_item_id: str
    event_type: EventType
    run_id: str | None
    timestamp: datetime
    actor: str
    payload: dict[str, Any] = field(default_factory=dict)
    prev_event_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d


def init_db(path: Path | None = None) -> None:
    global _db_path
    if path is not None:
        _db_path = Path(path)
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS transitions (
              transition_id TEXT PRIMARY KEY,
              work_item_id TEXT NOT NULL,
              event_type TEXT NOT NULL,
              run_id TEXT,
              timestamp TEXT NOT NULL,
              actor TEXT,
              payload_json TEXT,
              prev_event_id TEXT,
              payload_hash TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_work_item ON transitions(work_item_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_event_type ON transitions(event_type, timestamp);
            """
        )


def _connect() -> sqlite3.Connection:
    if not _db_path.exists():
        init_db(_db_path)
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_event(row: sqlite3.Row) -> TransitionEvent:
    payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
    return TransitionEvent(
        transition_id=row["transition_id"],
        work_item_id=row["work_item_id"],
        event_type=row["event_type"],
        run_id=row["run_id"],
        timestamp=datetime.fromisoformat(row["timestamp"]),
        actor=row["actor"] or "",
        payload=payload,
        prev_event_id=row["prev_event_id"],
    )


def _find_existing(
    conn: sqlite3.Connection, work_item_id: str, event_type: str, run_id: str | None
) -> sqlite3.Row | None:
    cur = conn.execute(
        "SELECT * FROM transitions WHERE work_item_id=? AND event_type=? AND "
        "((run_id IS NULL AND ? IS NULL) OR run_id=?) ORDER BY timestamp DESC LIMIT 1",
        (work_item_id, event_type, run_id, run_id),
    )
    return cur.fetchone()


def _latest_for_work_item(conn: sqlite3.Connection, work_item_id: str) -> sqlite3.Row | None:
    cur = conn.execute(
        "SELECT * FROM transitions WHERE work_item_id=? ORDER BY timestamp DESC LIMIT 1",
        (work_item_id,),
    )
    return cur.fetchone()


def record_event(
    event_type: EventType,
    work_item_id: str,
    run_id: str | None = None,
    actor: str = "",
    payload: dict[str, Any] | None = None,
) -> TransitionEvent:
    payload = payload or {}
    ts = _utc_now()
    p_hash = _payload_hash(payload)

    with _connect() as conn:
        existing = _find_existing(conn, work_item_id, event_type, run_id)
        if existing is not None and existing["payload_hash"] == p_hash:
            logger.debug(
                "transitions: noop duplicate %s for %s run_id=%s",
                event_type,
                work_item_id,
                run_id,
            )
            return _row_to_event(existing)

        prev = _latest_for_work_item(conn, work_item_id)
        prev_id = prev["transition_id"] if prev else None
        tid = _make_transition_id(work_item_id, event_type, run_id, ts)

        conn.execute(
            "INSERT INTO transitions(transition_id, work_item_id, event_type, run_id, "
            "timestamp, actor, payload_json, prev_event_id, payload_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                tid,
                work_item_id,
                event_type,
                run_id,
                ts.isoformat(),
                actor,
                json.dumps(payload, default=str),
                prev_id,
                p_hash,
            ),
        )
        conn.commit()

        return TransitionEvent(
            transition_id=tid,
            work_item_id=work_item_id,
            event_type=event_type,
            run_id=run_id,
            timestamp=ts,
            actor=actor,
            payload=payload,
            prev_event_id=prev_id,
        )


def get_events(work_item_id: str) -> list[TransitionEvent]:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT * FROM transitions WHERE work_item_id=? ORDER BY timestamp ASC",
            (work_item_id,),
        )
        return [_row_to_event(r) for r in cur.fetchall()]


def events_by_type(event_type: str, since: datetime | None = None) -> list[TransitionEvent]:
    with _connect() as conn:
        if since is not None:
            cur = conn.execute(
                "SELECT * FROM transitions WHERE event_type=? AND timestamp>=? ORDER BY timestamp ASC",
                (event_type, since.isoformat()),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM transitions WHERE event_type=? ORDER BY timestamp ASC",
                (event_type,),
            )
        return [_row_to_event(r) for r in cur.fetchall()]


def replay_check(work_item_id: str) -> dict[str, Any]:
    events = get_events(work_item_id)
    anomalies: list[dict[str, Any]] = []

    seen_run_ids: dict[str, TransitionEvent] = {}
    seen_dispatch = False
    prev_ts: datetime | None = None
    expected_prev: str | None = None

    for ev in events:
        if prev_ts is not None and ev.timestamp < prev_ts:
            anomalies.append(
                {"type": "out_of_order", "transition_id": ev.transition_id, "timestamp": ev.timestamp.isoformat()}
            )
        if ev.prev_event_id != expected_prev:
            anomalies.append(
                {
                    "type": "broken_chain",
                    "transition_id": ev.transition_id,
                    "expected_prev": expected_prev,
                    "actual_prev": ev.prev_event_id,
                }
            )

        if ev.event_type == "dispatch.accepted":
            seen_dispatch = True
        elif ev.event_type in ("return.received", "return.direct_closeout", "github.closeout"):
            if not seen_dispatch and ev.event_type == "return.received":
                anomalies.append(
                    {"type": "return_without_dispatch", "transition_id": ev.transition_id, "run_id": ev.run_id}
                )

        if ev.run_id:
            prior = seen_run_ids.get(ev.run_id)
            if prior is not None and prior.event_type == ev.event_type and prior.timestamp != ev.timestamp:
                anomalies.append(
                    {
                        "type": "duplicate_run_id",
                        "run_id": ev.run_id,
                        "transition_ids": [prior.transition_id, ev.transition_id],
                    }
                )
            seen_run_ids[ev.run_id] = ev

        expected_prev = ev.transition_id
        prev_ts = ev.timestamp

    return {
        "valid_chain": not anomalies,
        "events": [e.to_dict() for e in events],
        "anomalies": anomalies,
    }


def summary(window_days: int = 7) -> dict[str, Any]:
    since = _utc_now() - timedelta(days=window_days)
    with _connect() as conn:
        cur = conn.execute(
            "SELECT event_type, COUNT(*) AS n FROM transitions WHERE timestamp>=? GROUP BY event_type",
            (since.isoformat(),),
        )
        counts = {r["event_type"]: r["n"] for r in cur.fetchall()}
        total_cur = conn.execute(
            "SELECT COUNT(*) AS n FROM transitions WHERE timestamp>=?", (since.isoformat(),)
        )
        total = total_cur.fetchone()["n"]
    return {
        "window_days": window_days,
        "since": since.isoformat(),
        "total": total,
        "by_event_type": counts,
    }


def register_transition_tools(mcp: Any) -> None:
    """Register MCP tools that expose the transition log."""

    @mcp.tool()
    def transition_events(work_item_id: str) -> list[dict[str, Any]]:
        """Return chronological transition events for a Work Item."""
        return [e.to_dict() for e in get_events(work_item_id)]

    @mcp.tool()
    def transition_replay_check(work_item_id: str) -> dict[str, Any]:
        """Validate the event chain for a Work Item and report anomalies."""
        return replay_check(work_item_id)
