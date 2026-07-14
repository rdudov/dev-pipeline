from __future__ import annotations

import json

import pytest

from dev_pipeline import lifecycle
from dev_pipeline.lifecycle import LifecycleStore, RunIdentity


def test_store_orders_events_and_projects_separate_outcomes(tmp_path):
    store = LifecycleStore(tmp_path)
    identity = RunIdentity.create("example-task")

    first = store.append(
        identity,
        "attempt_started",
        {"attempt_origin": "new_owner_session", "repository": "/example"},
    )
    store.append(identity, "run_started", {"run_operation": "native_session_start"})
    store.append(identity, "native_session_discovered", {"native_session_id": "session-1"})
    store.append(identity, "run_completed", {"exit_code": 0})
    last = store.append(identity, "attempt_completed")

    assert first["sequence"] == 1
    assert last["sequence"] == 5
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["attempt"]["outcome"] == "completed"
    assert state["attempt"]["native_session_id"] == "session-1"
    assert state["run"]["outcome"] == "completed"
    assert state["run"]["run_operation"] == "native_session_start"


def test_store_refuses_to_advance_corrupt_ledger(tmp_path):
    (tmp_path / "events.jsonl").write_text('{"sequence": 1}\nnot-json\n')
    store = LifecycleStore(tmp_path)

    with pytest.raises(RuntimeError, match="corrupt at line 2"):
        store.append(RunIdentity.create("example-task"), "attempt_started")

    assert len((tmp_path / "events.jsonl").read_text().splitlines()) == 2


def test_store_rejects_reuse_by_another_attempt(tmp_path):
    store = LifecycleStore(tmp_path)
    first = RunIdentity.create("example-task")
    store.append(first, "attempt_started")

    with pytest.raises(RuntimeError, match="different attempt"):
        store.append(RunIdentity.create("example-task"), "attempt_started")

    assert len((tmp_path / "events.jsonl").read_text().splitlines()) == 1


def test_store_retries_short_writes(tmp_path, monkeypatch):
    real_write = lifecycle.os.write
    write_sizes: list[int] = []

    def short_write(descriptor, content):
        limited = content[: max(1, len(content) // 2)]
        written = real_write(descriptor, limited)
        write_sizes.append(written)
        return written

    monkeypatch.setattr(lifecycle.os, "write", short_write)
    store = LifecycleStore(tmp_path)
    event = store.append(RunIdentity.create("example-task"), "attempt_started")

    assert len(write_sizes) > 1
    assert json.loads((tmp_path / "events.jsonl").read_text()) == event
