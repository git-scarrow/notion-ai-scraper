from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import transitions as T


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "transitions.db"
    monkeypatch.setattr(T, "_db_path", db)
    T.init_db(db)
    return db


def test_record_and_get_round_trip() -> None:
    ev = T.record_event(
        "dispatch.accepted",
        work_item_id="wi-1",
        run_id="run-1",
        actor="lab_dispatcher",
        payload={"status": "consumed"},
    )
    fetched = T.get_events("wi-1")
    assert len(fetched) == 1
    assert fetched[0].transition_id == ev.transition_id
    assert fetched[0].event_type == "dispatch.accepted"
    assert fetched[0].payload == {"status": "consumed"}
    assert fetched[0].run_id == "run-1"
    assert fetched[0].prev_event_id is None


def test_deterministic_id_same_inputs() -> None:
    ts = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)
    a = T._make_transition_id("wi-1", "dispatch.accepted", "run-1", ts)
    b = T._make_transition_id("wi-1", "dispatch.accepted", "run-1", ts)
    assert a == b
    c = T._make_transition_id("wi-1", "dispatch.accepted", "run-2", ts)
    assert a != c


def test_chain_integrity_threads_prev_event_id() -> None:
    e1 = T.record_event("dispatch.accepted", "wi-2", run_id="r1", actor="dispatcher")
    time.sleep(0.001)
    e2 = T.record_event("return.received", "wi-2", run_id="r1", actor="webhook")
    time.sleep(0.001)
    e3 = T.record_event("intake.triggered", "wi-2", run_id="r1", actor="intake")

    events = T.get_events("wi-2")
    assert [e.transition_id for e in events] == [e1.transition_id, e2.transition_id, e3.transition_id]
    assert events[0].prev_event_id is None
    assert events[1].prev_event_id == e1.transition_id
    assert events[2].prev_event_id == e2.transition_id


def test_replay_check_valid_chain() -> None:
    T.record_event("dispatch.accepted", "wi-3", run_id="r1", actor="dispatcher")
    time.sleep(0.001)
    T.record_event("return.received", "wi-3", run_id="r1", actor="webhook")
    result = T.replay_check("wi-3")
    assert result["valid_chain"] is True
    assert result["anomalies"] == []
    assert len(result["events"]) == 2


def test_replay_check_detects_return_without_dispatch() -> None:
    T.record_event("return.received", "wi-4", run_id="r1", actor="webhook")
    result = T.replay_check("wi-4")
    assert result["valid_chain"] is False
    types = {a["type"] for a in result["anomalies"]}
    assert "return_without_dispatch" in types


def test_summary_counts_by_type() -> None:
    T.record_event("dispatch.accepted", "wi-5", run_id="r1")
    T.record_event("dispatch.accepted", "wi-6", run_id="r2")
    T.record_event("return.received", "wi-5", run_id="r1")
    s = T.summary(window_days=7)
    assert s["total"] == 3
    assert s["by_event_type"]["dispatch.accepted"] == 2
    assert s["by_event_type"]["return.received"] == 1


def test_idempotent_re_record_does_not_duplicate() -> None:
    e1 = T.record_event(
        "dispatch.accepted", "wi-7", run_id="r1", actor="dispatcher", payload={"k": 1}
    )
    e2 = T.record_event(
        "dispatch.accepted", "wi-7", run_id="r1", actor="dispatcher", payload={"k": 1}
    )
    assert e1.transition_id == e2.transition_id
    assert len(T.get_events("wi-7")) == 1


def test_events_by_type_filters_and_since() -> None:
    T.record_event("dispatch.accepted", "wi-8", run_id="r1")
    T.record_event("return.received", "wi-8", run_id="r1")
    accepted = T.events_by_type("dispatch.accepted")
    assert len(accepted) == 1
    future = datetime.now(timezone.utc) + timedelta(days=1)
    assert T.events_by_type("dispatch.accepted", since=future) == []
